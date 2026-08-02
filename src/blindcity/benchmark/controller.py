"""Controller protocol: state channel in → lever settings out.

`human`, `agent_datahub`, and `agent_raw` all implement this. Slice 5 ships scripted
policies so the harness is testable without an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from blindcity.levers import LEVERS, defaults
from blindcity.sim.model import CityState


@runtime_checkable
class Controller(Protocol):
    """One decision step for one turn of a scenario."""

    name: str

    def decide(self, state: CityState, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        """Return a full or partial lever map for this turn.

        `channel` is arm-specific: SQL rows, catalog context, or human intent. Scripted
        controllers may ignore it. Partial maps are merged onto current levers by the harness.
        """
        ...


@dataclass
class FixedLeverController:
    """Always set the same levers (bad defaults, recovery policy, etc.)."""

    name: str
    levers: dict[str, float]

    def decide(self, state: CityState, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        return dict(self.levers)


@dataclass
class ScriptedController:
    """Turn-indexed lever maps; falls back to last defined or defaults."""

    name: str
    schedule: dict[int, dict[str, float]]
    fallback: dict[str, float] | None = None

    def decide(self, state: CityState, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        if turn in self.schedule:
            return dict(self.schedule[turn])
        if self.fallback is not None:
            return dict(self.fallback)
        return dict(state.levers)


def clamp_decision(raw: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in raw.items():
        if name in LEVERS:
            out[name] = LEVERS[name].clamp(float(value))
    return out


def merge_levers(current: dict[str, float], updates: dict[str, float]) -> dict[str, float]:
    base = dict(current) if current else defaults()
    base.update(clamp_decision(updates))
    # Ensure all eight levers present
    for name, lev in LEVERS.items():
        base.setdefault(name, lev.default)
    return base


# --- Calibrated policies for the infrastructure_neglect scenario -----------------

# Continues neglect: no recovery spend, high prices. Must never cross green.
BAD_POLICY: dict[str, float] = {
    "income_tax_rate": 0.03,
    "property_tax_rate": 0.003,
    "electricity_tariff": 0.85,
    "road_maintenance_budget": 0.0,
    "water_sewer_capex": 0.0,
    "transit_fare": 9.0,
    "zoning_release": 0.0,
    "power_contract_mode": 0.0,
}

# Hand-calibrated recovery: moderate taxes that fund services, hedge power, open zoning.
# Road/water budgets near the top of the calibrated range so recovery is reachable in 36 months.
GOOD_POLICY: dict[str, float] = {
    "income_tax_rate": 0.11,
    "property_tax_rate": 0.012,
    "electricity_tariff": 0.11,
    "road_maintenance_budget": 6_000_000.0,
    "water_sewer_capex": 5_500_000.0,
    "transit_fare": 1.5,
    "zoning_release": 0.60,
    "power_contract_mode": 2.0,  # hedged
}


def bad_controller() -> FixedLeverController:
    return FixedLeverController(name="bad_neglect", levers=BAD_POLICY)


def good_controller() -> FixedLeverController:
    return FixedLeverController(name="good_recovery", levers=GOOD_POLICY)
