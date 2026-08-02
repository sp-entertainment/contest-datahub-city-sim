"""Composite health index for scoring a scenario run.

Components (each in [0, 1]):
  - solvency: treasury and debt relative to city scale
  - satisfaction: mean citizen satisfaction
  - service: power service, water headroom, road condition
  - population: retention vs population at crisis onset

Weights and green threshold are a judged design choice — recorded in docs/DECISIONS.md.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from blindcity.sim.model import CityState

# Weights must sum to 1.0. Rationale: docs/DECISIONS.md (health index entry).
WEIGHTS: dict[str, float] = {
    "solvency": 0.20,
    "satisfaction": 0.30,
    "service": 0.30,
    "population": 0.20,
}

# "Recovered" means the composite crossed this threshold within the turn budget.
GREEN_THRESHOLD: float = 0.62

_WEIGHT_SUM = sum(WEIGHTS.values())
assert abs(_WEIGHT_SUM - 1.0) < 1e-9, f"WEIGHTS must sum to 1, got {_WEIGHT_SUM}"


@dataclass(frozen=True)
class HealthComponents:
    solvency: float
    satisfaction: float
    service: float
    population: float
    index: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# Cost to restore one fully worn road segment, and one unit of missing water capacity.
# These price the backlog in the same currency as debt; the water figure matches
# `systems.WATER_CAPEX_PER_UNIT` so the liability is what it would actually cost to close.
ROAD_RESTORE_COST_PER_SEGMENT = 20_000.0
WATER_RESTORE_COST_PER_UNIT = 6_000.0
# Load ratio the water system is expected to be held at. Anything above it is a backlog.
WATER_TARGET_RATIO = 0.7
# Scale of effective debt per capita. The debt term decays exponentially with this constant
# rather than clamping linearly to zero: a linear clamp pinned the neglect arm's solvency at a
# constant for all 36 turns, and a component that cannot move is a component that cannot be
# diagnosed. Exponential decay stays responsive at every debt level.
DEBT_PER_CAPITA_SCALE = 3_000.0


def deferred_maintenance_liability(state: CityState) -> float:
    """What it would cost today to undo the physical decay the city has let accumulate.

    Municipal finance calls this the deferred maintenance backlog, and it exists precisely
    because cash-only measures flatter a government that balances its books by letting the
    assets rot. Without it, the neglect arm of the benchmark scored *perfect* solvency: it
    spends nothing, so it repays its debt and builds months of cover while the roads fail.
    """
    road_backlog = 0.0
    if state.roads:
        mean_wear = sum(r.wear for r in state.roads) / len(state.roads)
        road_backlog = mean_wear * len(state.roads) * ROAD_RESTORE_COST_PER_SEGMENT

    needed_capacity = state.water.demand / WATER_TARGET_RATIO if state.water.demand else 0.0
    missing = max(0.0, needed_capacity - state.water.capacity)
    water_backlog = missing * WATER_RESTORE_COST_PER_UNIT

    return road_backlog + water_backlog


def solvency_score(state: CityState) -> float:
    """Map treasury, effective debt, and balance into [0, 1].

    Cover is measured in months of operating spend rather than raw treasury size, and debt
    includes the deferred maintenance backlog. Both choices exist to stop a do-nothing policy
    from scoring well: starving services raises cash cover and repays borrowings, so on cash
    alone neglect is indistinguishable from prudence.
    """
    pop = max(state.population(), 1)
    monthly_burn = max(state.budget.total_spend, 50_000.0 + pop * 2.0)
    # Comfortable buffer: ~6 months of spend in the treasury.
    months_cover = state.budget.treasury / monthly_burn
    t_term = _clamp01(months_cover / 6.0)
    effective_debt = state.budget.debt + deferred_maintenance_liability(state)
    debt_per = effective_debt / pop
    d_term = math.exp(-debt_per / DEBT_PER_CAPITA_SCALE)
    bal = state.budget.balance
    bal_term = _clamp01(0.5 + bal / (monthly_burn * 0.5))
    return _clamp01(0.30 * t_term + 0.50 * d_term + 0.20 * bal_term)


def satisfaction_score(state: CityState) -> float:
    return _clamp01(state.mean_satisfaction())


def service_score(state: CityState) -> float:
    """Power coverage, water headroom, and road condition — equal thirds."""
    if state.buildings:
        powered = sum(1 for b in state.buildings if b.power_served) / len(state.buildings)
    else:
        powered = 0.0
    # load_ratio 0.5 → good; 1.0 → strained; >1.2 → failing
    water = _clamp01(1.0 - max(0.0, state.water.load_ratio - 0.5) / 0.8)
    if state.roads:
        mean_wear = sum(r.wear for r in state.roads) / len(state.roads)
        mean_cong = sum(r.congestion for r in state.roads) / len(state.roads)
    else:
        mean_wear = 1.0
        mean_cong = 1.0
    roads = _clamp01(1.0 - 0.6 * mean_wear - 0.4 * mean_cong)
    # Outage fraction also hits power even if buildings currently show served
    power = _clamp01(powered * (1.0 - 0.5 * state.power.outage_fraction))
    return _clamp01((power + water + roads) / 3.0)


def population_score(state: CityState, baseline_population: int) -> float:
    """Retention vs the founding population.

    Half the founding population scores 0 and 120% scores 1, so simply holding steady lands
    around 0.71 and growth still registers. A scale that topped out at parity pinned this
    component at 1.0 for every turn of a successful run, which is no signal at all.
    """
    if baseline_population <= 0:
        return 1.0 if state.population() > 0 else 0.0
    ratio = state.population() / baseline_population
    return _clamp01((ratio - 0.5) / 0.7)


def health_index(state: CityState, baseline_population: int) -> HealthComponents:
    """Composite health in [0, 1] with component breakdown."""
    s = solvency_score(state)
    sat = satisfaction_score(state)
    svc = service_score(state)
    pop = population_score(state, baseline_population)
    index = (
        WEIGHTS["solvency"] * s
        + WEIGHTS["satisfaction"] * sat
        + WEIGHTS["service"] * svc
        + WEIGHTS["population"] * pop
    )
    index = _clamp01(index)
    return HealthComponents(
        solvency=s,
        satisfaction=sat,
        service=svc,
        population=pop,
        index=index,
    )


def is_green(components: HealthComponents, threshold: float = GREEN_THRESHOLD) -> bool:
    return components.index >= threshold


def describe_weights() -> dict[str, Any]:
    return {
        "weights": dict(WEIGHTS),
        "green_threshold": GREEN_THRESHOLD,
        "components": (
            "solvency",
            "satisfaction",
            "service",
            "population",
        ),
    }
