"""The closed loop, as a benchmark controller.

One implementation, instantiated twice. `agent_datahub` and `agent_raw` are the *same object*
with a different `CatalogSource`, which is the only way to make "they differ in exactly one thing"
a property of the code rather than a promise in a document. There is no `if mode == ...` anywhere
below, and there must never be: the moment behaviour branches on the mode, the headline result
measures the branch instead of the metadata.

The loop, per turn: hand the model the levers it currently holds and the turn number, let it
issue read-only SQL against the city's history until it has seen enough, take the levers it
sets, and return them to the harness.

What the model is NOT given, on purpose:
  - the health index, its components, or the green threshold
  - population, treasury, satisfaction, or any other aggregate as a number in the prompt
  - the scenario description, the crisis, or what was done to the city

All of that is discoverable from the warehouse through SQL, which is the entire premise: the
city is legible only through its data. Handing it over in the prompt would measure how well the
model reads a briefing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from blindcity.agent import runscope
from blindcity.agent.catalog import CatalogSource, NoCatalog
from blindcity.agent.llm import (
    LLM,
    LLMError,
    ToolResult,
    Turn,
    Usage,
    user_turn,
)
from blindcity.agent.monitor import Monitor, NoMonitor
from blindcity.agent.tools import ToolContext, dispatch, tool_declarations
from blindcity.levers import LEVERS
from blindcity.sim.model import CityState

# Tool calls the model may make per turn before it must commit. A budget rather than a limit on
# thinking: both modes get the same one, so a catalog that saves queries shows up as a better
# decision inside the budget, not as more queries.
DEFAULT_TOOL_BUDGET = 12

# How many past turns keep their query results in full. Beyond this the results are replaced by a
# one-line summary of what each query returned, while the model's own words and the queries it
# wrote are kept forever.
#
# The city is a moving target: rows read eight turns ago describe a city that no longer exists,
# and re-reading them costs tokens to be misled. What does not go stale is the reasoning -- what
# the model concluded, what it tried, and which queries were dead ends.
#
# Without any memory the agent re-derived the city from scratch every turn. Measured over one
# 12-turn run that meant 29 repeated `information_schema` queries, and the *same* fan-out join
# issued on four separate turns, each killed by the statement timeout after 45 seconds, because
# nothing carried the lesson forward.
RESULTS_KEPT_IN_FULL = 2

SYSTEM_PROMPT = """\
You are the city manager of a simulated city in crisis. Your job is to get the city healthy \
again within a limited number of turns by adjusting policy levers.

You cannot see the city. Everything you know about it must come from SQL queries against its \
data warehouse, which records one row per entity per simulated month for the city's entire \
history. Query it. The history before your first turn shows how the city got into this state, \
and is usually the fastest route to the cause.

Each turn you may issue several `sql_query` calls, then call `set_levers` with the changes you \
want. Levers persist between turns, so you only need to set what you are changing. Advancing to \
the next turn happens automatically once you commit.

Work like an analyst: find what is actually failing before you spend money on it. The city's \
budget is finite, and a lever set far past what the problem needs will cost more than it \
repairs. When you have decided, call `set_levers` and briefly say why.\
"""


@dataclass
class AgentTurn:
    """What the agent did on one turn, for the audit trail."""

    turn: int
    sql_calls: int
    queries: list[str]
    levers_set: dict[str, float]
    rationale: str
    usage: dict[str, Any]
    # Wall time for the whole turn, and the share of it spent executing tools. Everything not
    # covered by these plus usage['seconds'] is the loop's own overhead, which is the only way
    # to notice when time is going somewhere nobody is looking.
    seconds: float = 0.0
    tool_seconds: float = 0.0
    # An LLM failure, which costs the whole turn.
    error: str | None = None
    # Tool calls that failed. None of these cost the turn -- the model reads the error and adapts
    # within the same turn -- which is exactly why they must be recorded somewhere.
    #
    # Two kinds, kept apart because they mean opposite things. A model asking for a table that
    # does not exist is *working*: that is what exploration looks like, especially without a
    # catalog to read. A statement timeout or a dead warehouse is the harness failing the model,
    # and it silently costs a diagnosis the model asked for. Lumping them together produces a
    # warning that fires on every healthy run, which is the same as no warning at all.
    tool_errors: list[str] = field(default_factory=list)
    timed_out_queries: list[str] = field(default_factory=list)
    infrastructure_errors: list[str] = field(default_factory=list)
    # Levers the model asked for and did not get. Recorded because `levers_set` holds post-clamp
    # values only, so a model repeatedly asking for out-of-range settings left no trace at all.
    clamped: dict[str, str] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentController:
    """A `Controller` (see `blindcity.benchmark.controller`) driven by an LLM."""

    name: str
    llm: LLM
    conn: psycopg.Connection
    run_id: int
    catalog: CatalogSource = field(default_factory=NoCatalog)
    # Per-turn catalog signal. `NoMonitor` for both original modes, so their turn prompts stay
    # byte-identical; only `agent_datahub_live` supplies one.
    monitor: Monitor = field(default_factory=NoMonitor)
    tool_budget: int = DEFAULT_TOOL_BUDGET
    turn_budget: int | None = None
    history: list[AgentTurn] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    # Optional: rebuild the warehouse connection if it dies mid-run, re-scoping it to this run.
    reconnect: Callable[[], psycopg.Connection] | None = None

    def __post_init__(self) -> None:
        runscope.create_run_views(self.conn, self.run_id)
        runscope.scope_connection(self.conn, self.run_id)
        self._system = self._build_system_prompt()
        # One segment per decision turn. Kept segmented rather than as one flat list so age can
        # be measured in turns, which is what the compaction policy is expressed in.
        self._segments: list[list[Turn]] = []
        self._last_outcome: tuple[dict[str, float], dict[str, str], dict[str, str]] = ({}, {}, {})

    def _reconnect(self) -> psycopg.Connection:
        """Replace a dead warehouse connection, re-scoped to this run's views.

        Re-scoping is the part that is easy to forget: a fresh connection has the default
        search_path, so without it the agent would silently start reading every run pooled
        together instead of its own.
        """
        if self.reconnect is None:
            raise psycopg.OperationalError("no reconnect factory configured")
        conn = self.reconnect()
        runscope.scope_connection(conn, self.run_id)
        self.conn = conn
        return conn

    @staticmethod
    def _summarise(payload: dict[str, Any]) -> dict[str, Any]:
        """Shrink one tool result to what is still true later.

        An error stays verbatim -- that is the part worth remembering, and the whole reason the
        same fan-out join was written four times is that nothing remembered it the first time.
        A successful query keeps its shape (row count and columns) and drops its rows.
        """
        if "error" in payload:
            return {k: payload[k] for k in ("error", "timed_out") if k in payload}
        if "columns" in payload:
            return {
                "note": "results elided; re-query if you need these rows again",
                "row_count": payload.get("row_count"),
                "columns": payload.get("columns"),
            }
        return payload

    def _compact(self, segment: list[Turn]) -> list[Turn]:
        """Replace a past turn's query results with summaries, keeping calls and reasoning."""
        out: list[Turn] = []
        for turn in segment:
            if not turn.results:
                out.append(turn)
                continue
            out.append(
                Turn(
                    role=turn.role,
                    text=turn.text,
                    calls=turn.calls,
                    results=[
                        ToolResult(call=r.call, payload=self._summarise(r.payload))
                        for r in turn.results
                    ],
                )
            )
        return out

    def _conversation(self) -> list[Turn]:
        """The history the model sees this turn: recent turns in full, older ones compacted."""
        history: list[Turn] = []
        cutoff = len(self._segments) - RESULTS_KEPT_IN_FULL
        for i, segment in enumerate(self._segments):
            history.extend(segment if i >= cutoff else self._compact(segment))
        return history

    def _build_system_prompt(self) -> str:
        """System prompt = shared instructions + (catalog block, or nothing).

        The catalog block is appended, never interleaved, so the two modes' prompts are identical
        up to the byte where one of them stops.
        """
        block = self.catalog.context_block()
        if not block:
            return SYSTEM_PROMPT
        return f"{SYSTEM_PROMPT}\n\n{block}"

    def decide(self, state: CityState, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        """One turn of the loop. Returns the levers to apply."""
        ctx = ToolContext(
            conn=self.conn,
            run_id=self.run_id,
            levers=dict(state.levers),
            turn=turn,
            reconnect=self._reconnect,
        )
        # Provider-neutral: the controller never builds a wire format, so it cannot hand one mode
        # a differently-shaped conversation than the other.
        #
        # The conversation carries across turns. Governing a city is a multi-quarter problem --
        # a decision made now shows its effect two turns later -- and an agent that forgets each
        # quarter cannot run that loop. It can only react to a snapshot, which is what both modes
        # did: neither ever revisited a tax rate, because neither remembered setting one.
        segment: list[Turn] = [user_turn(self._turn_prompt(state, turn, monitored=True))]
        self._segments.append(segment)
        history = self._conversation()
        declarations = tool_declarations()
        queries: list[str] = []
        rationale = ""
        error: str | None = None
        turn_usage = Usage()
        turn_started = time.monotonic()
        # What actually took effect, as opposed to what was asked for. Carried to the next turn's
        # prompt: a value silently clamped to a bound is a decision the model did not make, and
        # until now it was never told. It saw only the net figure a quarter later, with no reason.
        applied: dict[str, float] = {}
        clamped: dict[str, str] = {}
        rejected: dict[str, str] = {}

        for _ in range(self.tool_budget):
            try:
                reply = self.llm.generate(
                    system=self._system, history=history, tools=declarations
                )
            except LLMError as exc:
                # A failed turn must not abort the run: the harness still advances a month, and
                # the mode is scored on a city it failed to steer. That is a real outcome, not an
                # exception, and silently retrying forever would hide it.
                error = str(exc)
                break

            turn_usage.add(reply.usage)
            if reply.text:
                rationale = reply.text

            if not reply.calls:
                break

            # Appended to both: `history` is what this turn's next model call sees, `segment` is
            # what later turns inherit. They are the same objects, so nothing can drift.
            model_turn = Turn(role="model", text=reply.text, calls=reply.calls)
            history.append(model_turn)
            segment.append(model_turn)
            results: list[ToolResult] = []
            for call in reply.calls:
                if call.name == "sql_query":
                    queries.append(str(call.args.get("query", "")))
                results.append(ToolResult(call=call, payload=dispatch(ctx, call.name, call.args)))
            result_turn = Turn(role="user", results=results)
            history.append(result_turn)
            segment.append(result_turn)

            # Committing ends the turn. Anything after this is the model second-guessing itself
            # on a city it can no longer observe, and both modes are held to the same rule.
            if any(c.name == "set_levers" for c in reply.calls):
                for r in results:
                    if r.call.name == "set_levers":
                        applied.update(r.payload.get("applied") or {})
                        clamped.update(r.payload.get("clamped") or {})
                        rejected.update(r.payload.get("rejected") or {})
                break

        self.usage.add(turn_usage)
        self.history.append(
            AgentTurn(
                turn=turn,
                sql_calls=len(queries),
                queries=queries,
                levers_set=dict(ctx.pending),
                rationale=rationale[:2000],
                usage=turn_usage.to_dict(),
                seconds=round(time.monotonic() - turn_started, 2),
                tool_seconds=round(sum(r.seconds for r in ctx.log), 2),
                error=error,
                tool_errors=[r.summary for r in ctx.log if not r.ok],
                timed_out_queries=[
                    str(r.args.get("query", ""))[:400] for r in ctx.log if r.timed_out
                ],
                infrastructure_errors=[
                    r.summary for r in ctx.log if r.timed_out or "warehouse unavailable" in r.summary
                ],
                clamped=dict(clamped),
                rejected=dict(rejected),
            )
        )
        self._last_outcome = (applied, clamped, rejected)
        return dict(ctx.pending)

    def _turn_prompt(self, state: CityState, turn: int, *, monitored: bool = False) -> str:
        """What the model sees each turn. Levers only — no city state, no score.

        `monitored` runs the per-turn catalog check. Off by default so the many places that build
        a prompt for inspection or for a test do not fire SQL as a side effect; `decide` is the
        one caller that asks for it.
        """
        levers = "\n".join(
            f"  {name}: {state.levers.get(name, LEVERS[name].default):g}" for name in LEVERS
        )
        remaining = ""
        if self.turn_budget is not None:
            left = self.turn_budget - turn
            remaining = f" You have {left} turn{'s' if left != 1 else ''} left, including this one."
        # What last turn's decision actually became. The tool result said so at the time, but the
        # turn ended on that call and the answer arrived a quarter late with no explanation of why
        # a figure differed from the one requested.
        applied, clamped, rejected = self._last_outcome
        confirmation = ""
        if applied or clamped or rejected:
            lines = ["Result of your last decision:"]
            if applied:
                lines.append(
                    "  applied: " + ", ".join(f"{k}={v:g}" for k, v in sorted(applied.items()))
                )
            for name, why in sorted(clamped.items()):
                lines.append(f"  {name}: {why} (outside its legal range)")
            for name, why in sorted(rejected.items()):
                lines.append(f"  {name}: rejected -- {why}")
            confirmation = "\n".join(lines) + "\n\n"

        signal = ""
        if monitored:
            block = self.monitor.block(self.conn, self.run_id, turn)
            if block:
                signal = block + "\n\n"

        return (
            f"Turn {turn + 1}.{remaining}\n\n"
            f"{confirmation}"
            f"Levers currently in force:\n{levers}\n\n"
            f"{signal}"
            "Investigate the city's data, then set the levers you want for this turn."
        )

    def report(self) -> dict[str, Any]:
        """Everything needed to audit the mode after the fact."""
        return {
            "controller": self.name,
            "model": self.llm.model,
            "catalog": getattr(self.catalog, "name", type(self.catalog).__name__),
            "monitor": getattr(self.monitor, "name", type(self.monitor).__name__),
            "tool_budget": self.tool_budget,
            "system_prompt_chars": len(self._system),
            "usage": self.usage.to_dict(),
            "turns": [
                {
                    "turn": t.turn,
                    "sql_calls": t.sql_calls,
                    "queries": t.queries,
                    "levers_set": t.levers_set,
                    "rationale": t.rationale,
                    "usage": t.usage,
                    "seconds": t.seconds,
                    "tool_seconds": t.tool_seconds,
                    "unaccounted_seconds": round(
                        t.seconds - t.tool_seconds - float(t.usage.get("seconds", 0.0)), 2
                    ),
                    "error": t.error,
                    "tool_errors": t.tool_errors,
                    "timed_out_queries": t.timed_out_queries,
                    "infrastructure_errors": t.infrastructure_errors,
                    "clamped": t.clamped,
                    "rejected": t.rejected,
                }
                for t in self.history
            ],
            # Run-level totals, so a degraded run is visible without reading every turn.
            "tool_failures": sum(len(t.tool_errors) for t in self.history),
            "timeouts": sum(len(t.timed_out_queries) for t in self.history),
            "infrastructure_failures": sum(len(t.infrastructure_errors) for t in self.history),
        }
