"""A controller that governs by asking DataHub's Analytics Agent, rather than by querying itself.

This is the manager-with-an-analyst shape. Each turn it states the situation in plain English —
which levers are in force, how many turns remain, what it changed last time — asks which levers to
move, and applies whatever lever values come back. It writes no SQL and holds no view of the city
of its own.

Two things it deliberately does *not* do, because either would turn the mode into a measurement of
our scaffolding instead of the advisor:

  * It does not tell the advisor anything about the city's state. Not the population, not the
    treasury, not a single reading. The advisor is connected to the same warehouse and the same
    catalog; finding out what is wrong is its job, and handing it a briefing would measure how
    well we summarise rather than how well it analyses.
  * It does not second-guess the answer. If the advice names no lever, the turn passes with no
    change. A controller that fell back to a policy of its own would be scoring that policy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from blindcity.agent.advisor import Advice, AnalyticsAgentAdvisor
from blindcity.levers import LEVERS
from blindcity.sim.model import CityState

BRIEF = """\
You are advising the manager of a city. The city's operational data is in the warehouse you are \
connected to, catalogued in DataHub: one row per entity per simulated month, covering citizens, \
buildings, roads, power, water, the municipal budget, and the policy levers in force each month.

The manager controls exactly eight levers and nothing else:

{levers}

Investigate the data and tell the manager which levers to change and to what values. Be specific: \
give a number for every lever you want changed, written as `lever_name = value`. Levers you do \
not mention will be left where they are.\
"""


@dataclass
class AdvisorController:
    """A `Controller` that delegates the analysis to the Analytics Agent."""

    name: str
    advisor: AnalyticsAgentAdvisor
    turn_budget: int | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def _question(self, state: CityState, turn: int) -> str:
        levers = "\n".join(
            f"  {name}: {LEVERS[name].minimum} to {LEVERS[name].maximum} ({LEVERS[name].unit}) "
            f"- {LEVERS[name].description}"
            for name in LEVERS
        )
        current = "\n".join(f"  {n}: {state.levers.get(n, LEVERS[n].default):g}" for n in LEVERS)

        if turn == 0:
            head = BRIEF.format(levers=levers)
        else:
            # After the first turn the advisor has the conversation; restating the brief each time
            # would crowd its own accumulated context.
            head = "Three months have passed since your last recommendation."

        remaining = ""
        if self.turn_budget is not None:
            left = self.turn_budget - turn
            remaining = (
                f" This is decision {turn + 1} of {self.turn_budget}; "
                f"{left} remain including this one."
            )

        return (
            f"{head}\n\n"
            f"Levers currently in force:\n{current}\n\n"
            f"Which levers should the manager change now, and to what values?{remaining}"
        )

    def decide(self, state: CityState, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        started = time.monotonic()
        advice: Advice = self.advisor.ask(self._question(state, turn))
        self.history.append(
            {
                "turn": turn,
                **advice.to_dict(),
                "seconds": round(time.monotonic() - started, 2),
            }
        )
        return dict(advice.levers)

    def report(self) -> dict[str, Any]:
        answered = [t for t in self.history if not t["error"]]
        acted = [t for t in self.history if t["levers"]]
        return {
            "controller": self.name,
            "model": f"analytics-agent@{self.advisor.base_url}",
            "catalog": "analytics_agent",
            "monitor": "none",
            "turns": self.history,
            # An advisor that answers and names no lever is a different failure from one that
            # never answered, and the mode's score cannot be read without knowing which happened.
            "answered_turns": len(answered),
            "acting_turns": len(acted),
            "advisor_errors": [t["error"] for t in self.history if t["error"]],
            "usage": {
                "prompt_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "calls": len(self.history),
                "seconds": round(sum(t["seconds"] for t in self.history), 2),
            },
        }
