"""Reading a decision out of the advisor's answer.

This mode's score is only worth something if the levers we applied are the levers the advisor
asked for. That went wrong once, silently and expensively: `road_maintenance_budget = 2e6` was
read as `2` by the prose regex, the parity feedback then told the advisor its budget *was* 2, and
the advisor agreed and restated it. Three turns of unfunded roads, and no artifact said a word.

So the cases below are the ones that failed, plus the shapes an LLM actually emits.
"""

from __future__ import annotations

import json

import pytest

from blindcity.agent.advisor import LeverBlockInvalid, extract_lever_block, parse_levers
from blindcity.agent.lever_review import (
    MAX_CLARIFICATIONS,
    LeverParseFailure,
    ReviewOutcome,
    read_decision,
)
from blindcity.levers import LEVERS


def block(payload: str) -> str:
    return f"Some reasoning about the city.\n\n```json\n{payload}\n```"


# --- The contract -------------------------------------------------------------------------------


def test_a_well_formed_block_is_read_exactly():
    out = extract_lever_block(block('{"income_tax_rate": 0.11, "road_maintenance_budget": 6000000}'))
    assert out == {"income_tax_rate": 0.11, "road_maintenance_budget": 6000000.0}


def test_an_empty_block_is_a_decision_not_an_absence():
    """`{}` means change nothing this turn. It must not be confused with no answer at all: one is
    the advisor deciding, the other is the advisor failing to."""
    assert extract_lever_block(block("{}")) == {}
    assert extract_lever_block("no block here at all") is None


def test_the_last_block_wins():
    """An analyst who shows a worked example first and the recommendation last is answering with
    the last one."""
    text = block('{"income_tax_rate": 0.04}') + "\n" + block('{"income_tax_rate": 0.11}')
    assert extract_lever_block(text) == {"income_tax_rate": 0.11}


@pytest.mark.parametrize(
    "payload",
    [
        '{"income_tax_rate": "moderate"}',      # a word is not a decision
        '{"income_tax_rate": null}',            # nor is a null
        '{"income_tax_rate": true}',            # bool is an int in Python; it is not a lever value
        '{"income_tax_rate": "0.11"}',          # a number as a string is still not a number
        '{"made_up_lever": 1}',                 # not one of the eight
        "[1, 2, 3]",                            # not an object
        "{not json at all",
    ],
)
def test_an_unusable_block_is_refused_rather_than_interpreted(payload):
    with pytest.raises(LeverBlockInvalid):
        extract_lever_block(block(payload))


def test_block_values_are_clamped_like_every_other_mode():
    out = extract_lever_block(block('{"income_tax_rate": 99}'))
    assert out == {"income_tax_rate": LEVERS["income_tax_rate"].maximum}


# --- Why the contract exists ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "written,meant",
    [
        ("road_maintenance_budget = 6e6", 6_000_000),   # the one that cost three turns
        ("road_maintenance_budget = 6M", 6_000_000),
        ("road_maintenance_budget = $6 million", 6_000_000),
        ("income_tax_rate = 11%", 0.11),
        ("Raise income_tax_rate to 11 percent", 0.11),
    ],
)
def test_the_prose_regex_still_gets_these_wrong(written, meant):
    """Kept as a regression record, not a wish. These are the cases that motivate the JSON block,
    and the regex is retained only as a cross-check -- so its failures must stay visible rather
    than quietly improve and let someone start trusting it again."""
    got = next(iter(parse_levers(written).values()))
    assert got != meant, f"{written!r} now parses correctly; the block is still authoritative"


def test_the_block_gets_them_all_right():
    """The same values, written as the contract requires."""
    out = extract_lever_block(block('{"road_maintenance_budget": 6000000, "income_tax_rate": 0.11}'))
    assert out == {"road_maintenance_budget": 6_000_000.0, "income_tax_rate": 0.11}


# --- The reviewer, and the clarification loop ----------------------------------------------------


class FakeLLM:
    """Returns scripted reviewer replies."""

    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def generate(self, *, system, history, tools=None):
        from blindcity.agent.llm import Reply

        self.calls += 1
        return Reply(text=self.replies.pop(0) if self.replies else "{}")


def test_the_reviewer_reads_an_answer_that_broke_the_contract():
    llm = FakeLLM(['{"levers": {"road_maintenance_budget": 6000000}, "vague": []}'])
    out = read_decision("I suggest about 6e6 on roads.", turn=3, llm=llm, ask_again=None)
    assert out.levers == {"road_maintenance_budget": 6_000_000.0}
    assert out.source == "reviewed"
    assert llm.calls == 1


def test_the_reviewer_is_never_asked_when_the_contract_was_followed():
    """The happy path must stay free and deterministic. A second model on every turn would put
    nondeterminism in the measurement path for no benefit."""
    llm = FakeLLM([])
    out = read_decision(block('{"income_tax_rate": 0.11}'), turn=0, llm=llm, ask_again=None)
    assert out.levers == {"income_tax_rate": 0.11}
    assert out.source == "contract"
    assert llm.calls == 0, "the reviewer ran on a well-formed answer"


def test_a_vague_answer_is_clarified_not_guessed():
    """'a moderate level' must produce a question, never a number. A reviewer allowed to guess
    would replace a parser that corrupts values with one that invents them."""
    llm = FakeLLM(['{"levers": {}, "vague": ["road_maintenance_budget"]}'])
    asked = []

    def ask_again(prompt):
        asked.append(prompt)
        return block('{"road_maintenance_budget": 3000000}')

    out = read_decision(
        "Raise road_maintenance_budget to a moderate level.", turn=5, llm=llm, ask_again=ask_again
    )
    assert out.levers == {"road_maintenance_budget": 3_000_000.0}
    assert out.source == "clarified"
    assert out.clarifications == 1
    assert "road_maintenance_budget" in asked[0]


def test_a_run_is_abandoned_when_the_answer_stays_unreadable():
    """Three attempts, then stop. A run whose levers were misread is measuring the parser rather
    than the catalog, and finishing it would produce a plausible number nobody could tell from a
    real one."""
    llm = FakeLLM(['{"levers": {}, "vague": ["water_sewer_capex"]}'] * (MAX_CLARIFICATIONS + 1))
    asked = []

    def ask_again(prompt):
        asked.append(prompt)
        return "still vague, sorry"

    with pytest.raises(LeverParseFailure) as info:
        read_decision("water_sewer_capex should go up a lot.", turn=7, llm=llm, ask_again=ask_again)

    assert info.value.turn == 7
    assert info.value.vague == ["water_sewer_capex"]
    assert len(asked) == MAX_CLARIFICATIONS
    # Every attempt is carried on the exception so the failure is diagnosable without a re-run.
    assert len(info.value.attempts) == MAX_CLARIFICATIONS + 1


def test_a_reviewer_that_cannot_be_read_is_fatal_immediately():
    """No reviewers reviewing reviewers. If the extractor's own output is unparseable, that is the
    end of it -- inventing a second one would only move the problem."""
    llm = FakeLLM(["I think the analyst meant six million."])
    with pytest.raises(LeverBlockInvalid):
        read_decision("about 6e6 on roads", turn=1, llm=llm, ask_again=None)


def test_the_reviewer_may_not_return_a_non_numeric_value():
    """Held to the same standard as the advisor: a word is not an extraction."""
    llm = FakeLLM(['{"levers": {"income_tax_rate": "moderate"}, "vague": []}'])
    out = read_decision("raise income_tax_rate", turn=2, llm=llm, ask_again=None)
    assert out.levers == {}


def test_prose_disagreeing_with_the_block_is_recorded():
    """The signal that went unnoticed for three runs while `2e6` was read as `2`. Diagnostic only
    -- the block wins -- but it must appear somewhere a person will see it."""
    text = "Spend road_maintenance_budget = 6e6.\n\n```json\n{\"road_maintenance_budget\": 6000000}\n```"
    out = read_decision(text, turn=4, llm=FakeLLM([]), ask_again=None)
    assert out.levers == {"road_maintenance_budget": 6_000_000.0}
    assert out.disagreements, "a 1,000,000x disagreement went unreported"
    assert "road_maintenance_budget" in out.disagreements[0]


def test_the_outcome_defaults_to_the_free_path():
    assert ReviewOutcome().source == "contract"
    assert ReviewOutcome().clarifications == 0


# --- The contract reaches the advisor ------------------------------------------------------------


def test_every_turn_restates_the_output_contract():
    """Twelve turns of accumulated context is a long way from where the format was explained, and
    a forgotten contract is not a worse answer -- it is an unreadable one."""
    from blindcity.agent.advisor_controller import AdvisorController

    class Stub:
        base_url = "http://x"
        tokens = {}  # noqa: RUF012

    class State:
        levers = {}  # noqa: RUF012

    controller = AdvisorController(name="agent_analytics", advisor=Stub(), turn_budget=12)
    for turn in (0, 1, 11):
        question = controller._question(State(), turn)
        assert "```json" in question, f"turn {turn} did not state the format"
        assert "6e6" in question, f"turn {turn} did not forbid scientific notation"
        assert "11%" in question, f"turn {turn} did not forbid percentages"


def test_the_contract_example_is_itself_valid():
    """The example in the brief is what the advisor will copy. If it does not parse, we have told
    it to do the wrong thing."""
    from blindcity.agent.advisor_controller import CONTRACT

    example = CONTRACT.split("```json")[1].split("```")[0].strip()
    assert extract_lever_block(f"```json\n{example}\n```") == json.loads(example)
