"""Composite health index for scoring a scenario run.

Components (each in [0, 1]):
  - solvency: treasury and debt relative to city scale
  - satisfaction: mean citizen satisfaction
  - service: power service, water headroom, road condition
  - population: retention vs population at crisis onset

Weights and green threshold are a judged design choice — recorded in docs/DECISIONS.md.
"""

from __future__ import annotations

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


def solvency_score(state: CityState) -> float:
    """Map treasury/debt/balance into [0, 1].

    Adequacy is measured against a few months of operating spend, not raw treasury
    size — extractive tax regimes that stockpile cash while the city decays should
    not look perfectly solvent. Deep debt and empty coffers score near 0.
    """
    pop = max(state.population(), 1)
    monthly_burn = max(state.budget.total_spend, 50_000.0 + pop * 2.0)
    # Comfortable buffer: ~6 months of spend in the treasury.
    months_cover = state.budget.treasury / monthly_burn
    t_term = _clamp01(months_cover / 6.0)
    debt_per = state.budget.debt / pop
    d_term = _clamp01(1.0 - debt_per / 1_500.0)
    bal = state.budget.balance
    bal_term = _clamp01(0.5 + bal / (monthly_burn * 0.5))
    return _clamp01(0.45 * t_term + 0.35 * d_term + 0.20 * bal_term)


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
    """Retention vs population at crisis onset. Growth above baseline caps at 1."""
    if baseline_population <= 0:
        return 1.0 if state.population() > 0 else 0.0
    ratio = state.population() / baseline_population
    # 100% retained → 1.0; 50% → 0.0; slight growth still 1.0
    return _clamp01((ratio - 0.5) / 0.5)


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
