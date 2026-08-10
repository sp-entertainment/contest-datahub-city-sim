"""Per-turn data-quality signal from the catalog, for the `agent_datahub_live` mode.

The static catalog block is the same text on turn 1 and turn 12: it describes the warehouse, not
the city. Assertions are the one part of DataHub that moves. They are declared in the catalog
(`schema_spec.ASSERTIONS`), emitted to DataHub alongside the schemas, and evaluated as real SQL,
so a failing assertion is the catalog telling the agent that a column has left the range its own
documentation says it should occupy.

**What this may and may not say.** It reports observations against documented expectations --
"load_ratio is 1.42, documented maximum 1.0". It never says which lever to pull. The distinction
is the whole reason the mode is defensible: an assertion is data quality, a recommendation would
be us playing the game on the agent's behalf and the comparison would measure our advice.

Injected rather than exposed as a tool on purpose. A tool measures whether the model thinks to
call it; injection measures whether the metadata helps, which is the question being asked.

**Injected into the prompt, but fetched from DataHub.** Those are different claims and only the
second one was ever in doubt. The bands, impacts and response lags rendered below are read out of
GMS at run start by `agent.guidance.fetch_guidance`; this module imports none of them. Until
2026-08-10 it imported the constants directly from `catalog/operational.py`, which meant the mode
would have scored exactly the same with DataHub switched off -- the catalog was decorative and the
Python tuple was doing the work. It also meant DataHub's own Analytics Agent, which can only read
the catalog, could not reach the guidance at any price, and came last of four modes because of it.
"""

from __future__ import annotations

from typing import Protocol

import psycopg

from blindcity.catalog.operational import Guidance, lever_breach, outcome_breach

# An assertion sweep runs a handful of aggregates over the current run. Bounded so a slow sweep
# degrades the block rather than the turn -- the agent's reasoning is never what waits here.
MONITOR_TIMEOUT_SECONDS = 20


class Monitor(Protocol):
    """Supplies a per-turn block appended to the turn prompt, or nothing."""

    name: str

    def block(self, conn: psycopg.Connection, run_id: int, turn: int) -> str: ...


class NoMonitor:
    """The default for both original modes: no per-turn injection at all."""

    name = "none"

    def block(self, conn: psycopg.Connection, run_id: int, turn: int) -> str:
        return ""


class AssertionMonitor:
    """Renders the catalog's expert guidance against the city as it stands now.

    The guidance is handed in, not imported. It is read out of DataHub once at run start by
    `agent.guidance.fetch_guidance`, so what steers the agent is what the catalog actually
    publishes -- and an expert who edits a band in the DataHub UI changes the next run without
    touching this file. There is no default: a monitor with nothing to assert is a bug, and
    constructing one has to be as hard to do by accident as running the mode without a catalog.
    """

    name = "assertions"

    def __init__(self, guidance: Guidance) -> None:
        self.guidance = guidance

    def _values(self, conn: psycopg.Connection) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{MONITOR_TIMEOUT_SECONDS}s'")
            for assertion in self.guidance.outcomes:
                cur.execute(assertion.sql)
                row = cur.fetchone()
                out[assertion.name] = None if row is None else row.get("value")
            cur.execute(
                "SELECT * FROM lever_monthly WHERE tick = (SELECT max(tick) FROM ticks)"
            )
            levers = cur.fetchone() or {}
        for guidance in self.guidance.levers:
            raw = levers.get(guidance.lever)
            out[guidance.lever] = None if raw is None else float(raw)
        return out

    def block(self, conn: psycopg.Connection, run_id: int, turn: int) -> str:
        try:
            values = self._values(conn)
            conn.rollback()  # read-only; do not leave the session idle in transaction
        except psycopg.Error:
            # Monitoring must never cost the turn. Without a block the agent is simply in the
            # position the other two modes are in anyway.
            try:
                conn.rollback()
            except psycopg.Error:
                pass
            return ""

        lines = [
            (
                "DataHub assertions. The catalog documents the operating envelope a well-run city "
                "holds to, authored against this warehouse. Readings outside it are flagged, and "
                "each lever carries how much moving it is actually worth."
            ),
        ]

        breaches: list[str] = []
        for assertion in self.guidance.outcomes:
            value = values.get(assertion.name)
            how = outcome_breach(assertion, value)
            if how is not None and value is not None:
                breaches.append(
                    f"  {assertion.table}.{assertion.column} = {value:.3g} -- {how}. "
                    f"{assertion.note}"
                )
        if breaches:
            lines.append("")
            lines.append(f"CITY STATE, outside documented range ({len(breaches)}):")
            lines.extend(breaches)
        else:
            lines.append("")
            lines.append("CITY STATE: every documented measure is inside its healthy range.")

        off_band: list[str] = []
        for guidance in self.guidance.levers:
            value = values.get(guidance.lever)
            how = lever_breach(guidance, value)
            if how is not None and value is not None:
                off_band.append(
                    f"  {guidance.lever} = {value:g} -- {how} [{guidance.impact}]. {guidance.note}"
                )
        if off_band:
            lines.append("")
            lines.append(
                f"LEVERS, outside documented range "
                f"({len(off_band)} of {len(self.guidance.levers)}):"
            )
            lines.extend(off_band)

        # How fast each system answers. Without it the agent reads a change still working its way
        # through as one that failed, and reverses a decision that was about to pay.
        lines.append("")
        lines.append("RESPONSE TIMES -- how long each system takes to reflect a change:")
        lines.extend(f"  {lag.column}: {lag.note}" for lag in self.guidance.lags)

        # Named explicitly rather than left out. A turn spent tuning a lever that cannot move the
        # outcome is a turn gone, and the agent has no way to know which those are from the data:
        # every lever looks equally adjustable from its declared range.
        negligible = [
            g.lever for g in self.guidance.levers if g.impact in ("low", "negligible")
        ]
        if negligible:
            lines.append("")
            lines.append(
                "LOW YIELD -- measured to move the outcome by under 2% across their whole range; "
                "set them once and spend the turn budget elsewhere: " + ", ".join(negligible)
            )
        return "\n".join(lines)


def build_monitor(name: str, gms_url: str | None = None) -> Monitor:
    if name == "assertions":
        # Fetched here, at construction, rather than lazily per turn: a catalog that goes missing
        # mid-run should not turn into a mode that quietly stops asserting halfway through.
        from blindcity.agent.guidance import fetch_guidance

        return AssertionMonitor(fetch_guidance(gms_url))
    if name == "none":
        return NoMonitor()
    raise ValueError(f"unknown monitor {name!r}; expected 'assertions' or 'none'")
