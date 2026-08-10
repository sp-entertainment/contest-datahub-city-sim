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
    OPERATIONAL_ASSERTIONS,
    OperationalAssertion,
    fires,
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
    """Evaluates the catalog's assertions against this run and reports what is out of range."""

    name = "assertions"

    def block(self, conn: psycopg.Connection, run_id: int, turn: int) -> str:
        fired: list[tuple[OperationalAssertion, float]] = []
        checked = 0
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = '{MONITOR_TIMEOUT_SECONDS}s'")
                for assertion in OPERATIONAL_ASSERTIONS:
                    cur.execute(assertion.sql)
                    row = cur.fetchone()
                    checked += 1
                    value = None if row is None else row.get("value")
                    if value is not None and fires(assertion, float(value)):
                        fired.append((assertion, float(value)))
            conn.rollback()  # read-only; do not leave the session idle in transaction
        except psycopg.Error:
            # A monitoring failure must not cost the turn. The agent simply gets no block, which
            # is the position the other two modes are in anyway.
            try:
                conn.rollback()
            except psycopg.Error:
                pass
            return ""

        if not checked:
            return ""

        lines = [
            (
                "DataHub monitoring. The catalog documents the operating conditions a functioning "
                "city's data holds to, and these are evaluated against the city as it stands now."
            ),
        ]
        if fired:
            lines.append(f"BREACHED ({len(fired)} of {checked}):")
            lines.extend(
                f"  {a.table}.{a.column} = {v:.3g} -- {a.message}" for a, v in fired
            )
        else:
            lines.append(f"  All {checked} operating conditions are met.")
        return "\n".join(lines)


def build_monitor(name: str) -> Monitor:
    if name == "assertions":
        return AssertionMonitor()
    if name == "none":
        return NoMonitor()
    raise ValueError(f"unknown monitor {name!r}; expected 'assertions' or 'none'")
