"""Every declared lineage edge must be demonstrable against the running simulation.

This is what stops `CAUSAL_EDGES` from becoming the thing this project set out to beat: a
hand-maintained lineage list that quietly drifts from the code. Declaring an edge is not enough —
it has to survive an experiment.
"""

from __future__ import annotations

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


def test_congestion_is_not_saturated():
    """Regression guard for the dead-column bug: congestion pinned at 1.0 for every segment.

    A column that never varies teaches the agent nothing and severs road wear from commute time.
    """
    from blindcity.sim.engine import run_simulation

    city = run_simulation(99, 2)
    assert city.roads
    saturated = sum(1 for r in city.roads if r.congestion >= 1.0)
    assert saturated < len(city.roads), "every road segment is fully congested — signal is dead"
    mean = sum(r.congestion for r in city.roads) / len(city.roads)
    assert 0.05 < mean < 0.98, f"mean congestion {mean:.3f} is not in an informative band"
