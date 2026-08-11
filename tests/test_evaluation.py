"""The comparison must not flatter the result.

`uv run eval` produces the number the submission is built around, so the ways it could mislead
are the things worth testing: spending money by accident, sorting modes into the order we hoped
for, and printing a single figure for a difference smaller than the run-to-run noise.
"""

from __future__ import annotations

import json
from typing import ClassVar

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


def test_a_bare_command_prints_help_rather_than_doing_anything(capsys):
    """`blindcity` with no subcommand must not pick one. The old `eval` guarded this by refusing
    a bare invocation because it would otherwise have run every mode and spent real money; the
    single CLI has no default action at all, which is the stronger version of the same rule."""
    import sys

    from blindcity.cli import main

    argv = sys.argv
    sys.argv = ["blindcity"]
    try:
        code = main()
    finally:
        sys.argv = argv
    assert code == 2
    assert "compare" in capsys.readouterr().out


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
            return "income_tax_rate = 0.11", ["SELECT 1"], ["execute_sql"]

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
    assert _rate_limit_delay(ValueError("HTTP 429 refused")) == _RATE_LIMIT_FLOOR

    # Every wait clears a full window, starting with the first. On a tokens-per-minute ceiling the
    # provider's own number is close to useless -- a refusal saying "try again in 281ms" was
    # followed by four failures, because one advisor question costs 57% of the whole minute and two
    # of them can never share a window.
    #
    # A ramp is the wrong shape here, and this is the assertion that says so: a run that ramped from
    # 8s spent its three sleeps on 14s, 16s and 32s, none of which could clear a minute, and lost
    # the turn anyway. There is no partial credit for waiting -- a retry inside the window is
    # refused exactly like the call that preceded it.
    waits = [_rate_limit_delay(ValueError("Rate limit reached ... try again in 281ms"), a)
             for a in range(4)]
    assert waits == sorted(waits) and waits[0] == _RATE_LIMIT_FLOOR
    assert all(w >= 60.0 for w in waits), f"a wait that cannot clear a 60s window is spent: {waits}"
    assert all(w <= 70.0 for w in waits), "waiting longer than a window buys nothing"


class _NullClient:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- Did the advisor read the catalog, or only have the option to? ------------------------------


class _StreamingClient:
    """An Analytics Agent whose SSE stream is fixed in advance."""

    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, json=None):
        return self

    def raise_for_status(self):
        return None

    def iter_lines(self):
        import json as _json

        for event in self.events:
            yield "data: " + _json.dumps(event)
        yield "data: [DONE]"


def test_a_failed_tool_call_is_not_recorded_as_a_read():
    """The first version of this kept names only, and reported 25 catalog reads on a run where
    every one of them returned null -- the metric meant to prove the guidance had been read was
    what concealed that it never was. The event shape is theirs, so this breaks quietly if it
    moves."""
    from blindcity.agent.advisor import AnalyticsAgentAdvisor

    advisor = AnalyticsAgentAdvisor()
    client = _StreamingClient([
        {"event": "TOOL_RESULT", "payload": {"tool_name": "search"}},
        {
            "event": "TOOL_RESULT",
            "payload": {"tool_name": "get_entities", "is_error": True, "result": "null data"},
        },
        {"event": "SQL", "payload": {"sql": "SELECT 1"}},
        {"event": "TOOL_RESULT", "payload": {"tool_name": "execute_sql"}},
        {"event": "TEXT", "payload": {"text": "roads are worn"}},
    ])

    answer, statements, tools = advisor._send(client, "conv", "what now?")
    assert answer == "roads are worn"
    assert statements == ["SELECT 1"]
    assert [t["name"] for t in tools] == ["search", "get_entities", "execute_sql"]
    assert [t["error"] for t in tools] == [None, "null data", None]


def test_a_turn_that_asked_for_the_guidance_and_was_refused_counts_as_no_read():
    """Only `search` and `get_entities` return `datasetProperties.customProperties`, which is where
    the guidance is published -- and only when they succeed. This is the exact shape of the run
    that scored 0.7527 while `get_entities` returned null on all twenty-five calls."""
    from blindcity.agent.advisor import Advice
    from blindcity.agent.advisor_controller import AdvisorController

    def call(name, error=None):
        return {"name": name, "error": error}

    class FakeAdvisor:
        base_url = "http://advisor"
        tokens: ClassVar[dict] = {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}
        rate_limited = 0

        def __init__(self):
            self.turn = 0

        def ask(self, question):
            # Turn 0 reads the catalog. Turn 1 asks and is refused, which is not a read.
            tools = (
                [call("search"), call("get_entities"), call("execute_sql")] if self.turn == 0
                else [call("get_entities", "no data"), call("execute_sql")]
            )
            self.turn += 1
            return Advice(
                question=question,
                answer='```json\n{"income_tax_rate": 0.11}\n```',
                tools=tools,
            )

    class State:
        # Populated, because turn 1 restates what last turn's advice became.
        levers: ClassVar[dict] = {"income_tax_rate": 0.11}

    controller = AdvisorController(name="agent_analytics", advisor=FakeAdvisor(), turn_budget=12)
    controller.decide(State(), 0, {})
    controller.decide(State(), 1, {})

    report = controller.report()
    assert report["tool_calls"] == {"get_entities": 2, "execute_sql": 2, "search": 1}
    assert report["failed_tool_calls"] == {"get_entities": 1}
    assert report["guidance_reads"] == 2, "a refused call was counted as a read"
    assert report["turns_reading_guidance"] == 1


# --- Publishing the catalog must not silently destroy someone's edits --------------------------


class _Drift:
    """Stands in for a DataHub that differs from the snapshot."""

    empty = False

    def __bool__(self):
        return True

    def lines(self):
        return ["  lever income_tax_rate: DataHub 0.12-0.16 | snapshot 0.1-0.14"]


def _apply(monkeypatch, *, overwrite, answer=None, drift=None):
    """Run apply_catalog against a fake GMS, returning (applied, prompted, log lines)."""
    from blindcity.catalog import apply as apply_mod

    drift = _Drift() if drift is None else drift

    monkeypatch.setattr(apply_mod, "catalog_drift", lambda gms: drift)
    published = {"n": 0}
    monkeypatch.setattr(
        apply_mod, "emit_all",
        lambda gms, **kw: published.__setitem__("n", published["n"] + 1) or "emitted",
    )
    asked, lines = [], []

    def ask(prompt):
        asked.append(prompt)
        return answer

    applied, _, _ = apply_mod.apply_catalog(
        "http://gms", overwrite=overwrite, ask=ask, log=lines.append
    )
    return applied, bool(asked), lines, published["n"]


def test_overwrite_true_replaces_without_asking(monkeypatch):
    applied, prompted, _, published = _apply(monkeypatch, overwrite=True)
    assert applied and not prompted and published == 1


def test_overwrite_false_keeps_datahub_without_asking(monkeypatch):
    """The run still happens -- it just uses DataHub's values. That is the point of the flag:
    edit a band in the UI, see how the agent responds, without the runner undoing the edit."""
    applied, prompted, lines, published = _apply(monkeypatch, overwrite=False)
    assert not applied and not prompted and published == 0
    assert any("leaving DataHub as it is" in line for line in lines)


def test_an_absent_flag_asks_and_shows_the_difference(monkeypatch):
    applied, prompted, lines, published = _apply(monkeypatch, overwrite=None, answer="y")
    assert applied and prompted and published == 1
    assert any("income_tax_rate" in line for line in lines), "the diff was not shown"


def test_answering_no_leaves_datahub_alone(monkeypatch):
    applied, prompted, _, published = _apply(monkeypatch, overwrite=None, answer="n")
    assert not applied and prompted and published == 0


def test_anything_other_than_yes_is_no(monkeypatch):
    """A prompt whose default is destructive is a prompt nobody should trust. Enter means no."""
    for answer in ("", "  ", "maybe", "Y E S"):
        applied, _, _, published = _apply(monkeypatch, overwrite=None, answer=answer)
        assert not applied and published == 0, f"{answer!r} was treated as consent"


def test_an_empty_datahub_is_filled_without_a_prompt(monkeypatch):
    """A fresh clone has nothing to lose, so it must not stop to ask. This is the case that has to
    work with no explanation for someone who just cloned the repo."""

    class Empty(_Drift):
        empty = True

        def lines(self):
            return []

    applied, prompted, _, published = _apply(monkeypatch, overwrite=None, drift=Empty())
    assert applied and not prompted and published == 1


def test_a_matching_datahub_is_republished_without_a_prompt(monkeypatch):
    class Same(_Drift):
        def __bool__(self):
            return False

        def lines(self):
            return []

    applied, prompted, _, published = _apply(monkeypatch, overwrite=None, drift=Same())
    assert applied and not prompted and published == 1


def test_the_tristate_flag_parses_both_words():
    from blindcity.cli import _tristate

    assert _tristate("true") is True and _tristate("TRUE") is True and _tristate("1") is True
    assert _tristate("false") is False and _tristate("no") is False and _tristate("0") is False
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        _tristate("perhaps")


def test_the_run_command_defaults_are_all_usable(monkeypatch, tmp_path):
    """Every `--flag` default must be something run_mode will actually accept.

    `--tool-budget` defaulted to None and was passed straight through, so the very first real
    invocation died with "NoneType cannot be interpreted as an integer" -- after publishing the
    catalog and seeding the warehouse. Parser defaults are code, and this is the cheapest place to
    prove they compose.
    """
    from blindcity.agent.controller import DEFAULT_TOOL_BUDGET
    from blindcity.cli import build_parser
    from blindcity.commands import run as run_cmd

    args = build_parser().parse_args(["run", "--mode", "good_policy", "--out", str(tmp_path / "r.json")])
    seen = {}

    class FakeRun:
        result = type("R", (), {
            "turns": [], "recovered": True, "green_turn": 1, "final_index": 0.5,
            "mode": "good_policy", "write_json": lambda self, p: None,
        })()
        report: ClassVar[dict] = {
            "model": "scripted", "catalog": "none", "turns": [],
            "usage": {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                      "calls": 0, "seconds": 0.0},
        }
        wall_seconds = 1.0

    def fake_run_mode(mode, **kw):
        seen.update(kw)
        return FakeRun()

    monkeypatch.setattr("blindcity.agent.run.run_mode", fake_run_mode)
    assert run_cmd.run(args) == 0

    assert isinstance(seen["tool_budget"], int) and seen["tool_budget"] == DEFAULT_TOOL_BUDGET
    # The scripted policies must never reach for a model or a catalog.
    assert seen["llm"] is None


def test_the_advisor_writes_its_own_transcript(tmp_path):
    """The advisor never touches RecordingLLM, because it never calls a model itself. Without its
    own recorder it produced a 0-byte transcript beside a run that spent 1.2M tokens -- the most
    expensive mode in the benchmark, and the only one whose artifacts said nothing had been said."""
    from blindcity.agent.advisor import Advice
    from blindcity.agent.advisor_controller import AdvisorController

    path = tmp_path / "t.jsonl"

    class FakeAdvisor:
        base_url = "http://advisor"
        tokens: ClassVar[dict] = {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}

        def ask(self, question):
            # The contract: prose reasoning, then a fenced JSON block carrying the decision.
            answer = 'Roads are worn.\n\n```json\n{"income_tax_rate": 0.11}\n```'
            return Advice(question=question, answer=answer,
                          levers={"income_tax_rate": 0.11}, queries=["SELECT 1"])

    controller = AdvisorController(
        name="agent_analytics", advisor=FakeAdvisor(), turn_budget=12, transcript=str(path)
    )
    controller.decide(_FakeState(), 0, {})

    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [x["phase"] for x in lines] == ["request", "response"]
    # The question is written before the call, so a hang still leaves evidence of what was asked.
    assert "eight levers" in lines[0]["question"]
    assert lines[1]["levers"] == {"income_tax_rate": 0.11}
    assert lines[1]["queries"] == ["SELECT 1"]


class _FakeState:
    levers: ClassVar[dict] = {}


def test_a_lost_turn_is_reported_in_the_comparison(tmp_path):
    """A run that produced no decision on some turns is not a worse strategy, it is a different
    experiment. It looked identical to a clean run in the table until now."""
    path = _write(tmp_path, "agent_analytics", 0.72, 4)
    side = path.with_suffix(".agent.json")
    report = json.loads(side.read_text(encoding="utf-8"))
    report["advisor_errors"] = ["rate limit", "rate limit"]
    side.write_text(json.dumps(report), encoding="utf-8")

    summaries = collect([path])
    assert summaries["agent_analytics"].lost_turns == 2
    out = markdown(summaries, threshold=0.62, seed=42, model="m")
    assert "Incomplete runs" in out and "lost 2 turn(s)" in out
