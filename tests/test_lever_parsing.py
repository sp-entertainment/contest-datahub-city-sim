"""Reading a decision out of the advisor's answer.

This mode's score is only worth something if the levers we applied are the levers the advisor
asked for. That went wrong once, silently and expensively: `road_maintenance_budget = 2e6` was
read as `2` by the prose regex that used to do this job, the parity feedback then told the advisor
its budget *was* 2, and the advisor agreed and restated it. Three turns of unfunded roads, and no
artifact said a word. That regex is gone; these are the shapes an LLM actually emits, held against
the reader that replaced it.
"""

from __future__ import annotations

import json

import pytest

from blindcity.agent.advisor import LeverBlockInvalid, extract_lever_block
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


def test_turn_zero_points_at_the_guidance_and_at_the_tool_that_works():
    """Told nothing, the advisor never looked. Told to use `get_entities`, it asked twenty-five
    times and got null every time -- that tool sends a query DataHub Core rejects wholesale. Naming
    `search` is not a style choice; it is the only path that returns the properties."""
    from blindcity.agent.advisor_controller import AdvisorController
    from blindcity.catalog.operational import GUIDANCE_PREFIX, LEVER_GUIDANCE_TABLE

    class Stub:
        base_url = "http://x"
        tokens = {}  # noqa: RUF012

    class State:
        levers = {}  # noqa: RUF012

    question = AdvisorController(name="agent_analytics", advisor=Stub(), turn_budget=12)._question(
        State(), 0
    )
    assert GUIDANCE_PREFIX in question
    assert LEVER_GUIDANCE_TABLE in question, "the dataset carrying the lever bands is not named"
    assert "`search`" in question, "nothing tells it how to read the properties"
    assert "get_entities" in question, "the tool that silently fails is not ruled out"


def test_the_brief_gives_an_address_and_never_a_band():
    """The mode's whole claim is that the guidance came out of DataHub. A band that leaked into the
    question would make the run a measurement of our prompt wearing DataHub's name."""
    from blindcity.agent.advisor_controller import catalog_pointer
    from blindcity.catalog.operational import LEVER_GUIDANCE, OUTCOME_ASSERTIONS

    pointer = catalog_pointer()
    for g in LEVER_GUIDANCE:
        assert g.note not in pointer
        for edge in (g.low, g.high):
            # 0.0 and 1.0 and 2 are ordinary numbers that appear in URNs and prose; the bands worth
            # protecting are the ones an agent could not have guessed.
            if edge not in (0.0, 1.0, 2.0):
                assert f"{edge:g}" not in pointer, f"{g.lever}'s band leaked into the brief"
    for a in OUTCOME_ASSERTIONS:
        assert a.note not in pointer


def test_the_contract_example_is_itself_valid():
    """The example in the brief is what the advisor will copy. If it does not parse, we have told
    it to do the wrong thing."""
    from blindcity.agent.advisor_controller import CONTRACT

    example = CONTRACT.split("```json")[1].split("```")[0].strip()
    assert extract_lever_block(f"```json\n{example}\n```") == json.loads(example)
