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
from blindcity.agent.tools import ToolContext, dispatch, tool_declarations
from blindcity.levers import LEVERS
from blindcity.sim.model import CityState

# Tool calls the model may make per turn before it must commit. A budget rather than a limit on
# thinking: both modes get the same one, so a catalog that saves queries shows up as a better
# decision inside the budget, not as more queries.
DEFAULT_TOOL_BUDGET = 12

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
    error: str | None = None


@dataclass
class AgentController:
    """A `Controller` (see `blindcity.benchmark.controller`) driven by an LLM."""

    name: str
    llm: LLM
    conn: psycopg.Connection
    run_id: int
    catalog: CatalogSource = field(default_factory=NoCatalog)
    tool_budget: int = DEFAULT_TOOL_BUDGET
    turn_budget: int | None = None
    history: list[AgentTurn] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        runscope.create_run_views(self.conn, self.run_id)
        runscope.scope_connection(self.conn, self.run_id)
        self._system = self._build_system_prompt()

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
        ctx = ToolContext(conn=self.conn, run_id=self.run_id, levers=dict(state.levers), turn=turn)
        # Provider-neutral: the controller never builds a wire format, so it cannot hand one mode
        # a differently-shaped conversation than the other.
        history: list[Turn] = [user_turn(self._turn_prompt(state, turn))]
        declarations = tool_declarations()
        queries: list[str] = []
        rationale = ""
        error: str | None = None
        turn_usage = Usage()
        turn_started = time.monotonic()

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

            history.append(Turn(role="model", text=reply.text, calls=reply.calls))
            results: list[ToolResult] = []
            for call in reply.calls:
                if call.name == "sql_query":
                    queries.append(str(call.args.get("query", "")))
                results.append(ToolResult(call=call, payload=dispatch(ctx, call.name, call.args)))
            history.append(Turn(role="user", results=results))

            # Committing ends the turn. Anything after this is the model second-guessing itself
            # on a city it can no longer observe, and both modes are held to the same rule.
            if any(c.name == "set_levers" for c in reply.calls):
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
            )
        )
        return dict(ctx.pending)

    def _turn_prompt(self, state: CityState, turn: int) -> str:
        """What the model sees each turn. Levers only — no city state, no score."""
        levers = "\n".join(
            f"  {name}: {state.levers.get(name, LEVERS[name].default):g}" for name in LEVERS
        )
        remaining = ""
        if self.turn_budget is not None:
            left = self.turn_budget - turn
            remaining = f" You have {left} turn{'s' if left != 1 else ''} left, including this one."
        return (
            f"Turn {turn + 1}.{remaining}\n\n"
            f"Levers currently in force:\n{levers}\n\n"
            "Investigate the city's data, then set the levers you want for this turn."
        )

    def report(self) -> dict[str, Any]:
        """Everything needed to audit the mode after the fact."""
        return {
            "controller": self.name,
            "model": self.llm.model,
            "catalog": getattr(self.catalog, "name", type(self.catalog).__name__),
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
                }
                for t in self.history
            ],
        }
