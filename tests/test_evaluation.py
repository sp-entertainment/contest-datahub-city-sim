"""The comparison must not flatter the result.

`uv run eval` produces the number the submission is built around, so the ways it could mislead
are the things worth testing: spending money by accident, sorting modes into the order we hoped
for, and printing a single figure for a difference smaller than the run-to-run noise.
"""

from __future__ import annotations

import json

import pytest

from blindcity.evaluation.compare import EXPECTED_ORDER, ModeSummary, collect, markdown


def _write(tmp_path, mode, index, green, tokens=1000, name=None):
    path = tmp_path / f"{name or mode}.json"
    path.write_text(json.dumps({
        "scenario_name": "infrastructure_neglect", "seed": 42, "controller_name": mode,
        "mode": mode, "run_id": "1", "turn_budget": 12, "green_threshold": 0.62,
        "baseline_population": 3235, "recovered": green is not None, "green_turn": green,
        "final_index": index, "turns": [], "meta": {},
    }), encoding="utf-8")
    path.with_suffix(".agent.json").write_text(json.dumps({
        "usage": {"total_tokens": tokens, "calls": 30, "seconds": 100.0},
        "turns": [{"sql_calls": 5}], "timeouts": 0, "infrastructure_failures": 0,
    }), encoding="utf-8")
    return path


def test_bare_eval_neither_spends_nor_pretends(capsys):
    """Defaulting to --live would spend money on a bare command; defaulting to --dry-run would let
    someone believe they had run the scored evaluation when they had not. So it refuses."""
    from blindcity.evaluation.__main__ import main

    with pytest.raises(SystemExit) as exit_info:
        import sys
        argv = sys.argv
        sys.argv = ["eval"]
        try:
            raise SystemExit(main())
        finally:
            sys.argv = argv
    assert exit_info.value.code == 2
    assert "--dry-run" in capsys.readouterr().err


def test_ordering_is_reported_not_enforced(tmp_path):
    """If the modes do not come out in the order we expect, that is the finding. A comparison
    that sorted them into the expected order would hide exactly the result worth knowing."""
    _write(tmp_path, "agent_raw", 0.70, 5)
    _write(tmp_path, "agent_datahub", 0.60, 9)
    _write(tmp_path, "agent_datahub_live", 0.80, 3)
    report = markdown(
        collect(list(tmp_path.glob("*.json"))), threshold=0.62, seed=42, model="m"
    )
    assert "Ordering not as expected" in report
    assert "agent_datahub_live > agent_raw > agent_datahub" in report


def test_expected_ordering_is_recognised(tmp_path):
    _write(tmp_path, "agent_raw", 0.60, 9)
    _write(tmp_path, "agent_datahub", 0.65, 7)
    _write(tmp_path, "agent_datahub_live", 0.80, 3)
    report = markdown(
        collect(list(tmp_path.glob("*.json"))), threshold=0.62, seed=42, model="m"
    )
    assert "Ordering as expected" in report


def test_a_single_run_per_mode_says_it_has_no_variance_estimate(tmp_path):
    _write(tmp_path, "agent_raw", 0.60, 9)
    _write(tmp_path, "agent_datahub", 0.65, 7)
    report = markdown(collect(list(tmp_path.glob("*.json"))), threshold=0.62, seed=42, model="m")
    assert "no variance estimate" in report


def test_a_gap_smaller_than_the_spread_is_called_out(tmp_path):
    """Three paired runs of this benchmark produced gaps of +0.045, +0.043 and -0.040 between the
    same two modes. A comparison that printed a mean without that context invites a conclusion the
    data does not support."""
    _write(tmp_path, "agent_raw", 0.60, 9, name="raw-a")
    _write(tmp_path, "agent_raw", 0.68, 7, name="raw-b")
    _write(tmp_path, "agent_datahub", 0.65, 7, name="hub-a")
    _write(tmp_path, "agent_datahub", 0.66, 7, name="hub-b")
    report = markdown(collect(list(tmp_path.glob("*.json"))), threshold=0.62, seed=42, model="m")
    assert "not distinguishable from noise" in report


def test_degraded_runs_are_named(tmp_path):
    path = _write(tmp_path, "agent_datahub", 0.65, 7)
    side = json.loads(path.with_suffix(".agent.json").read_text(encoding="utf-8"))
    side["timeouts"] = 4
    side["infrastructure_failures"] = 4
    path.with_suffix(".agent.json").write_text(json.dumps(side), encoding="utf-8")
    report = markdown(collect([path]), threshold=0.62, seed=42, model="m")
    assert "Degraded runs" in report


def test_summary_keeps_every_run_not_just_the_mean():
    s = ModeSummary(mode="agent_raw", runs=0)
    for v in (0.61, 0.68, 0.63):
        s.runs += 1
        s.final_index.append(v)
    assert s.index_spread == pytest.approx(0.07)
    assert len(s.to_dict()["final_index"]) == 3, "individual runs must survive into the artifact"


def test_expected_order_matches_the_modes_that_exist():
    from blindcity.agent.run import MODES

    assert set(EXPECTED_ORDER) == set(MODES)
