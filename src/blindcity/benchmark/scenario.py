"""Scenario definitions: a seedable crisis plus a turn budget.

A scenario is only useful if it is both recoverable and losable under some lever policies.
Calibration evidence lives in tests and in docs/DECISIONS.md.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from blindcity.levers import defaults
from blindcity.rng import RNG
from blindcity.sim.city_init import create_city
from blindcity.sim.engine import clamp_levers
from blindcity.sim.model import CityState
from blindcity.sim.systems import step_month


@dataclass(frozen=True)
class Scenario:
    """A named crisis the city starts in, with a fixed controller turn budget."""

    name: str
    seed: int
    # Months of neglect applied before the controller takes over.
    crisis_months: int
    # Controller turns (each turn advances `months_per_turn` simulated months).
    turn_budget: int
    months_per_turn: int = 1
    # Lever settings during the crisis setup phase (neglect / shock).
    crisis_levers: dict[str, float] = field(default_factory=dict)
    description: str = ""

    @property
    def recovery_months(self) -> int:
        return self.turn_budget * self.months_per_turn


# Neglect during the setup phase: starve roads/water, expensive power/transit, weak revenue
# so the treasury cannot quietly balloon into a false "solvent" reading.
_NEGLECT: dict[str, float] = {
    "income_tax_rate": 0.04,
    "property_tax_rate": 0.004,
    "electricity_tariff": 0.65,
    "road_maintenance_budget": 0.0,
    "water_sewer_capex": 0.0,
    "transit_fare": 8.0,
    "zoning_release": 0.0,
    "power_contract_mode": 0.0,  # spot
}


INFRASTRUCTURE_CRISIS = Scenario(
    name="infrastructure_neglect",
    seed=42,
    crisis_months=60,  # 5 years of neglect
    turn_budget=36,  # 3 years of recovery attempts
    months_per_turn=1,
    crisis_levers=_NEGLECT,
    description=(
        "Five years of infrastructure neglect, underfunded services, and high utility costs "
        "leave roads worn, water strained, power unreliable, satisfaction depressed, the "
        "treasury thin, and population below its founding size. A fiscal/infrastructure shock "
        "is applied at onset. The controller has 36 monthly turns to restore the composite "
        "health index above green."
    ),
)


def apply_crisis_shock(state: CityState) -> None:
    """Sharpen the crisis so it is clearly below green without waiting decades.

    Neglect alone can leave a large treasury if any tax is nonzero; the shock represents
    a sudden debt reckoning and capacity failure on top of the worn infrastructure.
    """
    state.budget.treasury = min(state.budget.treasury, 80_000.0)
    state.budget.debt = max(state.budget.debt, 8_000_000.0)
    state.budget.balance = min(state.budget.balance, -20_000.0)
    state.water.capacity = max(100.0, state.water.capacity * 0.35)
    for r in state.roads:
        r.wear = min(1.0, max(r.wear, 0.55) + 0.15)
    # Recompute congestion after wear shock so service score sees it.
    from blindcity.sim.systems import compute_congestion, compute_water_load

    compute_congestion(state)
    compute_water_load(state)
    for c in state.citizens:
        c.satisfaction = min(c.satisfaction, 0.32)


def build_crisis_state(
    scenario: Scenario,
    on_month: Callable[[CityState], None] | None = None,
) -> tuple[CityState, int]:
    """Materialise the city at crisis onset.

    Returns (state, baseline_population). Baseline is the founding population (tick 0),
    so the population component measures retention through the crisis, not a tautology
    of "100% of whoever is left at onset".

    `on_month` is called once at founding and after every simulated month of the crisis. The
    agent arms use it to write the neglect history into the warehouse: they diagnose the city
    exclusively through SQL, so a city whose past does not exist in Postgres is a city with no
    discoverable cause. Without it the agent's first turn opens on an empty table.

    It is deliberately *not* called after the shock, which alters the city without advancing the
    clock — a second write at the same tick would collide on the primary key. The shock first
    becomes visible in the data at the end of the controller's first turn, which is also when a
    real administration would first see it.
    """
    lev = clamp_levers({**defaults(), **scenario.crisis_levers})
    state = create_city(scenario.seed, lev)
    baseline_pop = state.population()
    if on_month is not None:
        on_month(state)
    parent = RNG(scenario.seed)
    for _ in range(scenario.crisis_months):
        step_month(state, parent.stream("tick"))
        if on_month is not None:
            on_month(state)
    apply_crisis_shock(state)
    return state, baseline_pop


def snapshot_levers(state: CityState) -> dict[str, float]:
    return dict(state.levers)


def scenario_to_dict(scenario: Scenario) -> dict[str, Any]:
    return {
        "name": scenario.name,
        "seed": scenario.seed,
        "crisis_months": scenario.crisis_months,
        "turn_budget": scenario.turn_budget,
        "months_per_turn": scenario.months_per_turn,
        "crisis_levers": dict(scenario.crisis_levers),
        "description": scenario.description,
    }


def clone_state(state: CityState) -> CityState:
    """Deep copy for isolation between arms / policies."""
    return deepcopy(state)
