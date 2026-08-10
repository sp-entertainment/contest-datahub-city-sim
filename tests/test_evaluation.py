"""The comparison must not flatter the result.

`uv run eval` produces the number the submission is built around, so the ways it could mislead
are the things worth testing: spending money by accident, sorting modes into the order we hoped
for, and printing a single figure for a difference smaller than the run-to-run noise.
"""

from __future__ import annotations

import json

import pytest

from blindcity.evaluation.compare import EXPECTED_ORDER, ModeSummary, collect, markdown


def _write(tmp_path, mode, index, green, tokens=1000, name=None, model="gpt-5.6-luna"):
    path = tmp_path / f"{name or mode}.json"
    path.write_text(json.dumps({
        "scenario_name": "infrastructure_neglect", "seed": 42, "controller_name": mode,
        "mode": mode, "run_id": "1", "turn_budget": 12, "green_threshold": 0.62,
        "baseline_population": 3235, "recovered": green is not None, "green_turn": green,
        "final_index": index, "turns": [], "meta": {},
    }), encoding="utf-8")
    path.with_suffix(".agent.json").write_text(json.dumps({
        "model": model,
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


# --- The advisor mode is a separate service, so parity has to be checked at runtime -----------


def test_advisor_refuses_a_mismatched_model():
    """The three agent modes share one client and a test stops them diverging on model or
    reasoning budget. `agent_analytics` is a separate service with its own configuration, so the
    same guarantee has to be enforced when it runs -- a silent mismatch would produce a number
    that looks comparable and is not."""
    import httpx

    from blindcity.agent.advisor import AnalyticsAgentAdvisor, LLMMismatch

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "some-other-model", "has_key": True})

    advisor = AnalyticsAgentAdvisor("http://advisor.test")
    advisor._client = lambda: httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(LLMMismatch, match="some-other-model"):
        advisor.preflight(expected_model="gpt-5.6-luna")


def test_advisor_accepts_a_matching_model():
    import httpx

    from blindcity.agent.advisor import AnalyticsAgentAdvisor

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "gpt-5.6-luna", "has_key": True})

    advisor = AnalyticsAgentAdvisor("http://advisor.test")
    advisor._client = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    advisor.preflight(expected_model="gpt-5.6-luna")  # must not raise


def test_advisor_refuses_when_it_has_no_key():
    import httpx

    from blindcity.agent.advisor import AnalyticsAgentAdvisor, LLMMismatch

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "gpt-5.6-luna", "has_key": False})

    advisor = AnalyticsAgentAdvisor("http://advisor.test")
    advisor._client = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMMismatch, match="no API key"):
        advisor.preflight(expected_model="gpt-5.6-luna")


def test_lever_parsing_is_strict_about_names_and_ranges():
    """The advisor answers in free text, so the parser is forgiving about formatting. It must not
    be forgiving about which levers exist or what values are legal, or the mode scores the parser
    rather than the advice."""
    from blindcity.agent.advisor import parse_levers
    from blindcity.levers import LEVERS

    text = (
        "Set **income_tax_rate**: 0.11 and road_maintenance_budget = 5,000,000. "
        "Also transit_fare -> 1.5, and made_up_lever = 42. "
        "Finally income_tax_rate = 0.9 as the corrected figure."
    )
    out = parse_levers(text)
    assert "made_up_lever" not in out, "an invented lever was accepted"
    assert out["road_maintenance_budget"] == 5_000_000.0, "thousands separators broke parsing"
    assert out["transit_fare"] == 1.5
    # Last mention wins -- analysts restate the recommendation in a closing summary -- and the
    # out-of-range value is clamped rather than taken literally.
    assert out["income_tax_rate"] == LEVERS["income_tax_rate"].maximum


def test_the_report_names_the_model_the_runs_actually_used(tmp_path):
    """`$LLM_MODEL` was printed as the model on every comparison, because the header echoed the
    command line rather than the runs. A results table that cannot say which model produced it is
    not a record of anything."""
    paths = [
        _write(tmp_path, "agent_raw", 0.71, 6),
        _write(tmp_path, "agent_datahub", 0.74, 5),
    ]
    report = markdown(collect(paths), threshold=0.62, seed=42, model="$LLM_MODEL")
    assert "`gpt-5.6-luna`" in report
    assert "$LLM_MODEL" not in report


def test_the_report_refuses_to_compare_modes_that_ran_different_models(tmp_path):
    """The A/B rests entirely on the modes differing in catalog context alone. Two models means
    every gap has two candidate explanations, and the table would give no sign of it."""
    paths = [
        _write(tmp_path, "agent_raw", 0.71, 6, model="gpt-4o"),
        _write(tmp_path, "agent_datahub", 0.74, 5, model="gpt-5.6-luna"),
    ]
    report = markdown(collect(paths), threshold=0.62, seed=42, model="whatever")
    assert "did not run the same model" in report
    assert "`gpt-4o`: agent_raw" in report
    assert "`gpt-5.6-luna`: agent_datahub" in report


def test_the_advisor_does_not_count_as_a_model_mismatch(tmp_path):
    """`agent_analytics` reports its endpoint, not a model id -- the model lives inside a service
    we do not own, and its parity is enforced by preflight() at runtime instead. Letting that
    string into the comparison would flag every four-mode run as mismatched."""
    paths = [
        _write(tmp_path, "agent_raw", 0.71, 6),
        _write(tmp_path, "agent_datahub", 0.74, 5),
        _write(tmp_path, "agent_analytics", 0.69, 5, model="analytics-agent@http://localhost:8100"),
    ]
    report = markdown(collect(paths), threshold=0.62, seed=42, model="x")
    assert "did not run the same model" not in report
    assert "`gpt-5.6-luna`" in report


# --- The advisor must not silently forfeit turns ------------------------------------------------


def test_a_rate_limited_question_is_re_put_not_forfeited(monkeypatch):
    """A rate limit is the mode being denied its turn, not the mode failing to govern the city.

    The other three modes absorb these inside their own HTTP client and lose nothing. The advisor
    calls a service that raises straight through, so without a retry it drops the turn -- two of
    twelve went that way once DataHub context doubled the prompt size.
    """
    from blindcity.agent import advisor as advisor_mod

    monkeypatch.setattr(advisor_mod.time, "sleep", lambda s: None)
    calls = {"n": 0}

    class Adv(advisor_mod.AnalyticsAgentAdvisor):
        def _client(self):
            raise AssertionError("should not be reached")

        def _send(self, client, conv, question):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError(
                    "Rate limit reached for gpt-5.6-luna ... Please try again in 1.631s."
                )
            return "income_tax_rate = 0.11", ["SELECT 1"]

        def start(self, client):
            return "conv"

    adv = Adv()
    monkeypatch.setattr(adv, "_client", lambda: _NullClient())
    out = adv.ask("what now?")

    assert out.error is None, out.error
    assert out.levers == {"income_tax_rate": 0.11}
    assert calls["n"] == 3
    assert adv.rate_limited == 2


def test_a_real_failure_is_reported_rather_than_retried(monkeypatch):
    """Only rate limits are worth re-putting. A dead service or an unparseable stream is a real
    result for this mode and must not be papered over by trying again."""
    from blindcity.agent import advisor as advisor_mod

    monkeypatch.setattr(advisor_mod.time, "sleep", lambda s: None)
    calls = {"n": 0}

    class Adv(advisor_mod.AnalyticsAgentAdvisor):
        def _send(self, client, conv, question):
            calls["n"] += 1
            raise ValueError("the engine exploded")

        def start(self, client):
            return "conv"

    adv = Adv()
    monkeypatch.setattr(adv, "_client", lambda: _NullClient())
    out = adv.ask("what now?")

    assert calls["n"] == 1, "a non-rate-limit failure was retried"
    assert "engine exploded" in out.error


def test_the_rate_limit_delay_is_read_from_the_provider(monkeypatch):
    """The provider states its own delay; a floor applies because a tokens-per-minute refusal
    clears when the window rolls, which is often later than the number it suggests."""
    from blindcity.agent.advisor import _RATE_LIMIT_FLOOR, _rate_limit_delay

    assert _rate_limit_delay(ValueError("something else entirely")) is None
    assert _rate_limit_delay(ValueError("Rate limit reached ... try again in 1.6s")) == _RATE_LIMIT_FLOOR
    assert _rate_limit_delay(ValueError("Rate limit reached ... try again in 90s")) == 90.0
    assert _rate_limit_delay(ValueError("HTTP 429 refused")) == _RATE_LIMIT_FLOOR


class _NullClient:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
