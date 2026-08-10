"""Prove each operational assertion separates a recovering city from a failing one.

An assertion that fires while the city is healing is worse than no assertion: it points the agent
at a system that is already fixed and costs it a turn it cannot get back. So every detector is
held to both halves of the property — it must fire under neglect *and* fall silent under recovery.

Runs the simulation in memory. No database, no API key, a couple of seconds.
"""

from __future__ import annotations

import pytest

from blindcity.benchmark.controller import BAD_POLICY, GOOD_POLICY, merge_levers
from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS, build_crisis_state, clone_state
from blindcity.catalog.operational import (
    OPERATIONAL_ASSERTIONS,
    TREND_MONTHS,
    fires,
)
from blindcity.rng import RNG
from blindcity.sim.systems import step_month

# The last few turns are what matters: by then a working policy has had time to show it works, and
# an assertion still firing is a false alarm rather than a slow response.
SETTLED_FROM_TURN = 8


def _series(levers: dict[str, float]) -> list[dict[str, float]]:
    """Per-turn snapshot of every quantity the assertions read."""
    sc = INFRASTRUCTURE_CRISIS
    state, _ = build_crisis_state(sc)
    state = clone_state(state)
    parent = RNG(sc.seed)
    out: list[dict[str, float]] = []
    for turn in range(sc.turn_budget):
        state.levers = merge_levers(state.levers, dict(levers))
        for _ in range(sc.months_per_turn):
            step_month(state, parent.stream("tick"))
        roads = state.roads or []
        out.append(
            {
                "road_wear": sum(r.wear for r in roads) / len(roads) if roads else 0.0,
                "water_load": state.water.load_ratio,
                "population": float(state.population()),
                "satisfaction": state.mean_satisfaction(),
            }
        )
    return out


def _value(assertion_name: str, series: list[dict[str, float]], turn: int) -> float:
    """Reproduce in Python what each assertion's SQL computes over the warehouse."""
    now = series[turn]
    # The SQL looks back TREND_MONTHS *months*; a turn is months_per_turn of them.
    back = max(0, turn - TREND_MONTHS // INFRASTRUCTURE_CRISIS.months_per_turn)
    then = series[back]
    if assertion_name == "road_wear_saturated":
        return now["road_wear"]
    if assertion_name == "water_demand_exceeds_capacity":
        return now["water_load"]
    if assertion_name == "population_declining":
        return now["population"] - then["population"]
    if assertion_name == "satisfaction_depressed":
        return now["satisfaction"]
    raise AssertionError(f"no reference implementation for {assertion_name!r}")


@pytest.fixture(scope="module")
def trajectories():
    return {"good": _series(GOOD_POLICY), "bad": _series(BAD_POLICY)}


@pytest.mark.parametrize("assertion", OPERATIONAL_ASSERTIONS, ids=lambda a: a.name)
def test_assertion_fires_on_a_failing_city(assertion, trajectories):
    """Silent through five years of neglect is decoration, not monitoring."""
    fired = [
        turn
        for turn in range(SETTLED_FROM_TURN, INFRASTRUCTURE_CRISIS.turn_budget)
        if fires(assertion, _value(assertion.name, trajectories["bad"], turn))
    ]
    assert fired, f"{assertion.name} never fired under the neglect policy"


@pytest.mark.parametrize("assertion", OPERATIONAL_ASSERTIONS, ids=lambda a: a.name)
def test_assertion_is_silent_on_a_recovering_city(assertion, trajectories):
    """A false alarm steers the agent away from a policy that is working."""
    fired = [
        turn
        for turn in range(SETTLED_FROM_TURN, INFRASTRUCTURE_CRISIS.turn_budget)
        if fires(assertion, _value(assertion.name, trajectories["good"], turn))
    ]
    assert not fired, f"{assertion.name} false-alarmed under the recovery policy on turns {fired}"


def test_every_assertion_has_a_reference_implementation():
    """Guards the test itself: a new assertion with no Python twin would silently pass both
    checks above by never being exercised."""
    for assertion in OPERATIONAL_ASSERTIONS:
        _value(assertion.name, [{"road_wear": 0.0, "water_load": 0.0,
                                 "population": 1.0, "satisfaction": 0.5}], 0)


def test_the_misleading_metrics_stay_out():
    """Treasury and debt end healthy under *both* policies -- neglect gets there slightly faster,
    because a city that skips maintenance accumulates cash. An assertion on either would have
    reported sound finances in exactly the run that was bankrupt in every way that mattered."""
    watched = {a.column for a in OPERATIONAL_ASSERTIONS}
    assert "treasury" not in watched
    assert "debt" not in watched
    # Outage never clears ~0.17 even under recovery, so no threshold separates the two policies.
    assert "outage_fraction" not in watched
