"""Run the simulation for N years. Pure in-memory path and optional warehouse writer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from blindcity.levers import LEVERS, defaults
from blindcity.rng import RNG
from blindcity.sim.city_init import create_city
from blindcity.sim.model import CityState
from blindcity.sim.systems import step_month


def clamp_levers(raw: dict[str, float] | None) -> dict[str, float]:
    base = defaults()
    if not raw:
        return base
    out = dict(base)
    for name, value in raw.items():
        if name in LEVERS:
            out[name] = LEVERS[name].clamp(float(value))
    return out


def run_simulation(
    seed: int,
    years: int,
    levers: dict[str, float] | None = None,
    on_month: Callable[[CityState], None] | None = None,
    record_initial: bool = True,
) -> CityState:
    """Create a city and advance `years * 12` months.

    If `on_month` is provided it is called after each monthly step (and once at tick 0 when
    `record_initial` is True) so writers can snapshot history.
    """
    if years < 0:
        raise ValueError("years must be >= 0")
    lev = clamp_levers(levers)
    state = create_city(seed, lev)
    parent = RNG(seed)

    if record_initial and on_month is not None:
        on_month(state)

    months = years * 12
    for _ in range(months):
        # The month's variation comes from `step_month`, which derives each system's stream with
        # the tick folded into the name (`power:{tick}` etc.). This parent stream is therefore the
        # same every month by design — it is a namespace, not a per-month seed. Do not "fix" it by
        # indexing here: that changes every fingerprint and buys nothing.
        step_month(state, parent.stream("tick"))
        if on_month is not None:
            on_month(state)

    return state


def run_fingerprint(seed: int, years: int, levers: dict[str, float] | None = None) -> dict[str, Any]:
    """Convenience for tests: final-state fingerprint only."""
    return run_simulation(seed, years, levers=levers).fingerprint()
