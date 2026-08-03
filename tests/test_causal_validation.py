"""Every declared lineage edge must be demonstrable against the running simulation.

This is what stops `CAUSAL_EDGES` from becoming the thing this project set out to beat: a
hand-maintained lineage list that quietly drifts from the code. Declaring an edge is not enough —
it has to survive an experiment.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from blindcity.sim.causal import CAUSAL_EDGES
from blindcity.sim.causal_check import (
    CHECKS,
    orphan_checks,
    unchecked_edges,
    validate_edges,
)


def test_every_edge_has_a_check():
    missing = [(e.source, e.target) for e in unchecked_edges()]
    assert not missing, f"declared lineage edges with no experiment behind them: {missing}"


def test_no_checks_for_edges_that_no_longer_exist():
    assert not orphan_checks(), f"checks left behind by deleted edges: {orphan_checks()}"


def test_check_registry_covers_the_graph_exactly():
    assert len(CHECKS) == len({(e.source, e.target) for e in CAUSAL_EDGES})


@pytest.mark.parametrize(
    "edge", CAUSAL_EDGES, ids=lambda e: f"{e.source}->{e.target}"
)
def test_edge_is_real(edge):
    """Perturb the source, run the code that computes the target, require the target to move."""
    check = CHECKS.get((edge.source, edge.target))
    assert check is not None, f"no check registered for {edge.source} -> {edge.target}"
    ok, detail = check()
    assert ok, f"{edge.source} -> {edge.target} could not be demonstrated: {detail}"


def test_validate_edges_reports_every_edge():
    verdicts = validate_edges()
    assert len(verdicts) == len(CAUSAL_EDGES)
    failed = [(v.edge.source, v.edge.target, v.detail) for v in verdicts if not v.ok]
    assert not failed, f"unvalidated edges: {failed}"


def test_congestion_never_reaches_its_ceiling():
    """Regression guard for the dead-column bug, which happened twice.

    First every segment pinned at 1.0 from the start; then, after SEGMENT_CAPACITY was resized,
    the city outgrew the constant and the clamp began firing again late in long runs — 60% of
    rows by tick 240, and 100% at benchmark crisis onset, which is exactly the history an agent
    reads to diagnose the road problem.

    The earlier version of this test only asserted that *some* segment was unsaturated and that
    the mean sat below 0.98, which a 99%-pinned column passes. Congestion is now mapped through
    `1 - exp(-ratio)`, so no segment can reach the ceiling at any horizon or traffic level.
    """
    from blindcity.sim.engine import run_simulation

    for years in (2, 20):
        city = run_simulation(99, years)
        assert city.roads
        pinned = [r.segment_id for r in city.roads if r.congestion >= 0.999]
        assert not pinned, f"{len(pinned)} segments at the ceiling after {years}y"
        mean = sum(r.congestion for r in city.roads) / len(city.roads)
        assert 0.05 < mean < 0.95, f"mean congestion {mean:.3f} after {years}y is not informative"


def test_congestion_stays_ordered_as_traffic_rises():
    """The point of removing the clamp: a bad road and a much worse one must stay distinguishable.

    Under the old `min(1.0, ratio)` every segment past capacity read exactly 1.0, so a road at
    1.1x capacity and one at 6x were the same number. Note the map is asymptotic, not
    unbounded — beyond roughly 35x capacity `1 - exp(-ratio)` rounds to 1.0 in float64. That is
    far outside any traffic this simulation produces (observed ratios peak near 2x), so the
    band tested here is the one that exists.
    """
    from blindcity.sim.engine import run_simulation
    from blindcity.sim.systems import compute_congestion

    city = run_simulation(99, 2)
    readings = []
    for multiplier in (0.5, 1.0, 2.0, 5.0, 10.0):
        for r in city.roads:
            r.traffic = 90.0 * multiplier
        compute_congestion(city)
        readings.append(city.roads[0].congestion)

    assert all(a < b for a, b in pairwise(readings)), readings
    assert readings[-1] < 1.0, f"congestion hit its ceiling at 10x traffic: {readings}"


def test_congestion_is_informative_at_benchmark_crisis_onset():
    """Turn 0 of the scenario is where the agent has to work out that the roads are the problem.
    A constant column there is the one place saturation actually costs the benchmark."""
    from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS, build_crisis_state

    state, _ = build_crisis_state(INFRASTRUCTURE_CRISIS)
    values = [r.congestion for r in state.roads]
    assert max(values) < 0.999, "congestion is pinned at crisis onset"
    assert max(values) - min(values) > 0.05, "congestion carries no variation at crisis onset"
