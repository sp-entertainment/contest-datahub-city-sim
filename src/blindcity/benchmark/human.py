"""The `human` mode's controller: a person in a browser, plugged into the same harness.

`RunHarness.run` is a synchronous loop that calls `controller.decide()` once per turn. Every other
mode returns from `decide()` immediately. This one blocks until the browser submits a turn, which
is the whole trick: the human plays through the identical loop, the identical `health_index` call
and the identical `RunResult` as the agent modes, rather than through a second implementation of
the turn loop living in the web layer.

The web layer never touches the simulation. It hands lever settings to `submit()` and waits for the
tick to move; the harness owns the state, the stepping and the scoring.
"""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field
from typing import Any

from blindcity.sim.model import CityState

# A person reads a city, asks an analyst questions and thinks before committing. An hour of that is
# not a hang, so the wait is generous. It exists at all so a browser that is closed mid-run ends the
# process eventually instead of leaving a thread parked forever.
TURN_TIMEOUT_SECONDS = 3600.0


class HumanRunAbandoned(RuntimeError):
    """Nobody submitted a turn before the deadline."""


@dataclass
class HumanController:
    """Blocks each turn until the browser submits levers.

    Reports like the scripted policies do -- zeros for usage and the failure counters -- so
    `compare` needs no branch for a mode that calls no model. The one addition is per-turn wall
    seconds, which is real information about how a person played and leaks nothing about the city.
    """

    name: str = "human"
    turn_budget: int = 12
    turn_timeout: float = TURN_TIMEOUT_SECONDS

    _submissions: queue.Queue[dict[str, float]] = field(default_factory=queue.Queue, repr=False)
    _turn_seconds: list[float] = field(default_factory=list, repr=False)
    # Shared with the web layer, which reads it to tell the browser which turn it is on and
    # whether the run is over. Written here, never there.
    progress: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.progress.setdefault("turn", 0)
        self.progress.setdefault("turn_budget", self.turn_budget)
        self.progress.setdefault("complete", False)

    # --- the web layer's half -------------------------------------------------------------

    def submit(self, levers: dict[str, float]) -> None:
        """Hand one turn's levers to the waiting harness. Called from a request thread."""
        self._submissions.put(dict(levers))

    def finish(self) -> None:
        """Mark the run over, after the harness has returned."""
        self.progress["complete"] = True

    # --- the harness's half ---------------------------------------------------------------

    def decide(self, state: CityState, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        self.progress["turn"] = turn
        started = time.monotonic()
        try:
            levers = self._submissions.get(timeout=self.turn_timeout)
        except queue.Empty as exc:
            raise HumanRunAbandoned(
                f"no turn submitted within {self.turn_timeout:.0f}s at turn {turn}"
            ) from exc
        self._turn_seconds.append(round(time.monotonic() - started, 1))
        return levers

    def report(self) -> dict[str, Any]:
        return {
            "controller": self.name,
            # Not a model id, and `compare` exempts it from the model-parity check for that reason.
            "model": "human",
            "catalog": "analytics_agent",
            "monitor": "none",
            "turns": [],
            "usage": {
                "prompt_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
                "seconds": 0.0,
            },
            "tool_failures": 0,
            "timeouts": 0,
            "infrastructure_failures": 0,
            "turn_seconds": list(self._turn_seconds),
        }
