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
"""

from __future__ import annotations

from typing import Protocol

import psycopg

from blindcity.catalog.operational import (
    LEVER_GUIDANCE,
    OUTCOME_ASSERTIONS,
    lever_breach,
    outcome_breach,
)

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
    """Renders the catalog's expert guidance against the city as it stands now."""

    name = "assertions"

    def _values(self, conn: psycopg.Connection) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{MONITOR_TIMEOUT_SECONDS}s'")
            for assertion in OUTCOME_ASSERTIONS:
                cur.execute(assertion.sql)
                row = cur.fetchone()
                out[assertion.name] = None if row is None else row.get("value")
            cur.execute(
                "SELECT * FROM lever_monthly WHERE tick = (SELECT max(tick) FROM ticks)"
            )
            levers = cur.fetchone() or {}
        for guidance in LEVER_GUIDANCE:
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
        for assertion in OUTCOME_ASSERTIONS:
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
        for guidance in LEVER_GUIDANCE:
            value = values.get(guidance.lever)
            how = lever_breach(guidance, value)
            if how is not None and value is not None:
                off_band.append(
                    f"  {guidance.lever} = {value:g} -- {how} [{guidance.impact}]. {guidance.note}"
                )
        if off_band:
            lines.append("")
            lines.append(f"LEVERS, outside documented range ({len(off_band)} of {len(LEVER_GUIDANCE)}):")
            lines.extend(off_band)

        # Named explicitly rather than left out. A turn spent tuning a lever that cannot move the
        # outcome is a turn gone, and the agent has no way to know which those are from the data:
        # every lever looks equally adjustable from its declared range.
        negligible = [g.lever for g in LEVER_GUIDANCE if g.impact in ("low", "negligible")]
        if negligible:
            lines.append("")
            lines.append(
                "LOW YIELD -- measured to move the outcome by under 2% across their whole range; "
                "set them once and spend the turn budget elsewhere: " + ", ".join(negligible)
            )
        return "\n".join(lines)


def build_monitor(name: str) -> Monitor:
    if name == "assertions":
        return AssertionMonitor()
    if name == "none":
        return NoMonitor()
    raise ValueError(f"unknown monitor {name!r}; expected 'assertions' or 'none'")
