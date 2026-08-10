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

from blindcity.catalog.assertions import evaluate_assertions

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
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = '{MONITOR_TIMEOUT_SECONDS}s'")
            results = evaluate_assertions(conn, run_id=run_id)
            conn.rollback()  # read-only; do not leave the session idle in transaction
        except psycopg.Error:
            # A monitoring failure must not cost the turn. The agent simply gets no block, which
            # is the same position the other two modes are in.
            try:
                conn.rollback()
            except psycopg.Error:
                pass
            return ""

        if not results:
            return ""

        failing = [r for r in results if not r.passed]
        lines = [
            "DataHub data-quality assertions, evaluated against the city as it stands now.",
            "These compare the warehouse against the ranges and volumes the catalog documents.",
            "",
        ]
        if failing:
            lines.append(f"OUT OF RANGE ({len(failing)} of {len(results)}):")
            lines.extend(f"  {r.table}.{r.column}: {r.description} -- {r.detail}" for r in failing)
        else:
            lines.append(f"All {len(results)} assertions pass.")
        passing = len(results) - len(failing)
        if failing and passing:
            lines.append(f"  ({passing} other assertion(s) pass.)")
        return "\n".join(lines)


def build_monitor(name: str) -> Monitor:
    if name == "assertions":
        return AssertionMonitor()
    if name == "none":
        return NoMonitor()
    raise ValueError(f"unknown monitor {name!r}; expected 'assertions' or 'none'")
