"""Benchmark substrate: health index, scenario, harness, win/lose policies."""

from __future__ import annotations

from functools import cache
from itertools import pairwise
from pathlib import Path

from blindcity.benchmark.controller import (
    BAD_POLICY,
    GOOD_POLICY,
    FixedLeverController,
    bad_controller,
    good_controller,
)
from blindcity.benchmark.harness import run_scenario
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


@cache
def _run(levers: tuple[tuple[str, float], ...]):
    """Cached scenario run. Scenario runs are expensive and deterministic, so identical
    lever sets are executed once per session."""
    return run_scenario(
        INFRASTRUCTURE_CRISIS, FixedLeverController(name="probe", levers=dict(levers))
    )


def _with(policy: dict[str, float], **overrides: float):
    return _run(tuple(sorted({**policy, **overrides}.items())))


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


def _pop(n: int):
    return type("S", (), {"population": lambda self: n})()


def test_population_score_moves_with_retention():
    assert population_score(_pop(500), 1000) == 0.0
    assert population_score(_pop(1200), 1000) == 1.0
    # Holding steady is good but not a perfect score, so the component keeps responding
    # instead of pinning at 1.0 for every turn of a successful run.
    parity = population_score(_pop(1000), 1000)
    assert 0.0 < parity < 1.0
    assert population_score(_pop(750), 1000) < parity < population_score(_pop(1100), 1000)


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


def test_bad_policy_fails_scenario(tmp_path: Path):
    result = run_scenario(INFRASTRUCTURE_CRISIS, bad_controller(), mode="scripted")
    result.write_json(tmp_path / "scenario-bad.json")
    assert result.recovered is False, (
        f"bad policy must not reach green; final={result.final_index:.3f} "
        f"green_turn={result.green_turn}"
    )
    assert result.final_index < GREEN_THRESHOLD


def test_good_policy_recovers_scenario(tmp_path: Path):
    result = run_scenario(INFRASTRUCTURE_CRISIS, good_controller(), mode="scripted")
    result.write_json(tmp_path / "scenario-good.json")
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


# --- Regressions from the 2026-08-02 benchmark review ---------------------------------
#
# Every failure below was live at the time: solvency rewarded the neglect mode, water capex
# could not move its own score, and the road lever was flat across the bottom of its range.
# All three passed the range-style assertions above, which is the point — a component that
# is constant, inverted, or saturated is still "in [0, 1]".

COMPONENTS = ("solvency", "satisfaction", "service", "population")


def test_good_beats_bad_on_every_component():
    """Not just on the composite. Solvency used to be *higher* for the neglect mode, which
    spends nothing, so it repays its debt and builds months of cash cover while the roads
    fail. A fifth of the index was rewarding the losing policy."""
    good = _run(tuple(sorted(GOOD_POLICY.items()))).turns[-1].components
    bad = _run(tuple(sorted(BAD_POLICY.items()))).turns[-1].components
    for key in COMPONENTS:
        assert good[key] > bad[key], (
            f"{key}: recovery scored {good[key]:.3f} but neglect scored {bad[key]:.3f}"
        )


def test_neglect_cannot_look_solvent():
    """Deferred maintenance is a liability. A city that balances its books by letting the
    infrastructure rot must not read as financially healthy."""
    bad = _run(tuple(sorted(BAD_POLICY.items())))
    assert max(t.components["solvency"] for t in bad.turns) < 0.75


def test_defaults_do_not_recover_the_scenario():
    """The crisis must require action. If leaving every lever alone reaches green, the
    benchmark measures nothing about the controller."""
    assert _run(tuple(sorted(defaults().items()))).recovered is False


def test_water_capex_can_actually_buy_water_service():
    """The water lever was a trap: at every legal setting the load ratio stayed above the
    point where the water term scores anything, so spending on water cost solvency and
    bought no score. An agent that correctly diagnosed the water system was punished."""
    starved = _with(GOOD_POLICY, water_sewer_capex=0.0)
    funded = _with(GOOD_POLICY, water_sewer_capex=6_000_000.0)
    assert funded.turns[-1].components["service"] > starved.turns[-1].components["service"]
    assert funded.final_index > starved.final_index + 0.1


def test_spend_levers_respond_across_their_whole_range():
    """No flat zone. Both budgets used to saturate their underlying quantity at 0.0 or 1.0,
    which made every setting in the bottom of the range produce an identical score — right
    where a controller starting from the default will probe first."""
    for lever in ("road_maintenance_budget", "water_sewer_capex"):
        indices = [
            _with(GOOD_POLICY, **{lever: float(v)}).final_index
            for v in (0, 1_000_000, 2_000_000, 4_000_000)
        ]
        gaps = [b - a for a, b in pairwise(indices)]
        assert all(g > 0.01 for g in gaps), f"{lever} response is flat somewhere: {indices}"


def test_overspending_is_punished():
    """The optimum is interior, so the benchmark cannot be won by slamming every budget to
    its maximum without reading the city's actual condition."""
    tuned = _with(GOOD_POLICY, road_maintenance_budget=6_000_000.0)
    maxed = _with(GOOD_POLICY, road_maintenance_budget=8_000_000.0)
    assert maxed.final_index < tuned.final_index


def test_no_component_is_constant_over_a_run():
    """A component that never moves cannot be diagnosed, and cannot distinguish two modes."""
    good = _run(tuple(sorted(GOOD_POLICY.items())))
    for key in COMPONENTS:
        values = [t.components[key] for t in good.turns]
        assert max(values) - min(values) > 0.02, f"{key} is effectively constant: {values[0]:.3f}"
