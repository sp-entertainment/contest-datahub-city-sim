"""Benchmark substrate: health index, scenario, harness, win/lose policies."""

from __future__ import annotations

import json
from pathlib import Path

from blindcity.benchmark.controller import (
    BAD_POLICY,
    GOOD_POLICY,
    FixedLeverController,
    bad_controller,
    good_controller,
)
from blindcity.benchmark.harness import RunHarness, run_scenario
from blindcity.benchmark.health import (
    GREEN_THRESHOLD,
    WEIGHTS,
    health_index,
    population_score,
    service_score,
    solvency_score,
)
from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS, build_crisis_state
from blindcity.levers import defaults
from blindcity.sim.engine import run_simulation

SCRATCH = Path(r"C:\Users\spect\AppData\Local\Temp\grok-goal-62f45bb1ec6e\implementer")


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_health_index_in_unit_interval():
    state = run_simulation(42, years=1)
    h = health_index(state, baseline_population=state.population())
    assert 0.0 <= h.index <= 1.0
    for key in ("solvency", "satisfaction", "service", "population"):
        assert 0.0 <= getattr(h, key) <= 1.0


def test_health_components_move_under_lever_perturbation():
    """Range-only checks pass for constants; require components to MOVE."""
    healthy = run_simulation(
        99,
        years=2,
        levers={
            **defaults(),
            "income_tax_rate": 0.10,
            "road_maintenance_budget": 3_500_000.0,
            "water_sewer_capex": 3_000_000.0,
            "electricity_tariff": 0.12,
            "power_contract_mode": 2.0,
            "transit_fare": 1.5,
        },
    )
    sick = run_simulation(
        99,
        years=2,
        levers={
            **defaults(),
            "income_tax_rate": 0.02,
            "road_maintenance_budget": 0.0,
            "water_sewer_capex": 0.0,
            "electricity_tariff": 0.9,
            "power_contract_mode": 0.0,
            "transit_fare": 9.0,
        },
    )
    # Compare both against the same founding baseline so population is not tautological.
    founding = run_simulation(99, years=0).population()
    h_ok = health_index(healthy, baseline_population=founding)
    h_bad = health_index(sick, baseline_population=founding)
    assert h_ok.index > h_bad.index
    assert h_ok.satisfaction > h_bad.satisfaction
    assert h_ok.service > h_bad.service


def test_solvency_moves_with_treasury():
    state = run_simulation(5, years=1)
    base = solvency_score(state)
    state.budget.treasury = 50_000_000.0
    state.budget.debt = 0.0
    rich = solvency_score(state)
    state.budget.treasury = 0.0
    state.budget.debt = 20_000_000.0
    poor = solvency_score(state)
    assert rich > base > poor or rich > poor


def test_population_score_moves_with_retention():
    assert population_score(type("S", (), {"population": lambda self: 1000})(), 1000) == 1.0
    assert population_score(type("S", (), {"population": lambda self: 500})(), 1000) == 0.0
    mid = population_score(type("S", (), {"population": lambda self: 750})(), 1000)
    assert 0.0 < mid < 1.0


def test_crisis_state_is_unhealthy():
    state, baseline = build_crisis_state(INFRASTRUCTURE_CRISIS)
    h = health_index(state, baseline)
    assert h.index < GREEN_THRESHOLD, (
        f"crisis onset should be below green ({GREEN_THRESHOLD}), got {h.index:.3f}"
    )
    assert baseline > 0


def test_same_controller_same_seed_same_trajectory():
    a = run_scenario(INFRASTRUCTURE_CRISIS, good_controller())
    b = run_scenario(INFRASTRUCTURE_CRISIS, good_controller())
    assert [t.index for t in a.turns] == [t.index for t in b.turns]
    assert a.recovered == b.recovered
    assert a.final_index == b.final_index


def test_bad_policy_fails_scenario():
    result = run_scenario(INFRASTRUCTURE_CRISIS, bad_controller(), arm="scripted")
    out = SCRATCH / "scenario-bad.json"
    result.write_json(out)
    assert result.recovered is False, (
        f"bad policy must not reach green; final={result.final_index:.3f} "
        f"green_turn={result.green_turn}"
    )
    assert result.final_index < GREEN_THRESHOLD


def test_good_policy_recovers_scenario():
    result = run_scenario(INFRASTRUCTURE_CRISIS, good_controller(), arm="scripted")
    out = SCRATCH / "scenario-good.json"
    result.write_json(out)
    assert result.recovered is True, (
        f"good policy must reach green; final={result.final_index:.3f} "
        f"trajectory_end_components={result.turns[-1].components if result.turns else None}"
    )
    assert result.green_turn is not None
    assert result.final_index >= GREEN_THRESHOLD


def test_service_score_not_constant_across_policies():
    neglect = run_simulation(
        11,
        years=3,
        levers={**defaults(), "road_maintenance_budget": 0.0, "water_sewer_capex": 0.0},
    )
    care = run_simulation(
        11,
        years=3,
        levers={
            **defaults(),
            "road_maintenance_budget": 4_000_000.0,
            "water_sewer_capex": 3_000_000.0,
            "power_contract_mode": 2.0,
        },
    )
    assert service_score(care) > service_score(neglect)


def test_policies_differ_from_defaults():
    d = defaults()
    assert BAD_POLICY["road_maintenance_budget"] == 0.0
    assert GOOD_POLICY["road_maintenance_budget"] > d["road_maintenance_budget"]
    # Bad underfunds infrastructure; good spends to recover. Taxes alone are not the signal.
    assert GOOD_POLICY["water_sewer_capex"] > BAD_POLICY["water_sewer_capex"]
    assert GOOD_POLICY["power_contract_mode"] > BAD_POLICY["power_contract_mode"]
