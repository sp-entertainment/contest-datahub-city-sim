"""Read a decision out of an answer that did not follow the contract, or fail loudly.

`advisor_controller` asks the Analytics Agent to end every answer with a JSON block, and
`advisor.extract_lever_block` reads it deterministically. That is the whole path on a well-formed
turn: no second model, no ambiguity, nothing to get wrong.

This module is the exception handler for when the contract is broken. It exists because the thing
it replaces -- a regex over prose -- failed silently and expensively. `road_maintenance_budget =
2e6` was read as `2`, the parity feedback then told the advisor its budget *was* 2, and the advisor
agreed and restated it. One misread number became a three-turn policy of leaving the roads
unfunded, and nothing in the run reported a problem.

Two rules make this safe to have at all.

**The reviewer extracts; it never infers.** If it were allowed to decide that "a moderate level"
probably means three million, we would have replaced a parser that corrupts values with one that
invents them, and the second is far harder to catch. It may report a number only where the advisor
wrote one. Anything else is `vague`, which asks the advisor rather than guessing on its behalf.

**Its own output is parsed deterministically.** The reviewer answers in strict JSON and we
`json.loads` it. If the reviewer itself cannot be read, that is fatal on the spot -- there is no
second reviewer to review the reviewer, and inventing one would only move the problem.

When a lever stays unreadable after three clarifications the run is abandoned. That is deliberate
and it is the cheaper mistake: a run whose levers were misread is measuring the parser rather than
the catalog, and finishing it would produce a plausible-looking number nobody can distinguish from
a real one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from blindcity.agent.advisor import LeverBlockInvalid, extract_lever_block
from blindcity.levers import LEVERS

# How many times the advisor may be asked to restate an unreadable decision. Three is enough to
# ride out a formatting lapse and few enough that a genuinely confused advisor fails fast.
MAX_CLARIFICATIONS = 3

_SYSTEM = """\
You extract structured data from an analyst's written recommendation. You do not analyse the city, \
you do not form opinions about the levers, and you never supply a value the analyst did not state.

The analyst controls exactly these levers:

{levers}

Read the recommendation and reply with a single JSON object and nothing else:

{{"levers": {{"lever_name": number}}, "vague": ["lever_name"]}}

  * `levers` holds only levers the analyst gave a definite number for. Convert notation faithfully:
    `6e6` and `6 million` and `6M` are all 6000000. A percentage is a fraction: `11%` is 0.11.
  * `vague` names levers the analyst clearly wanted to change but gave no usable number for --
    "raise it moderately", "increase substantially", "somewhere between 3 and 5 million".
  * A lever the analyst did not mention, or explicitly said to leave alone, belongs in NEITHER
    list. Leaving a lever out is how "no change" is expressed.
  * If you cannot tell what number the analyst meant, put the lever in `vague`. Never guess. A
    wrong number is far worse than an admission that the text was unclear.\
"""

_CLARIFY = """\
Your last answer could not be read as a decision{why}.

Reply with ONLY the JSON block -- no prose, no explanation:

```json
{{"lever_name": number}}
```

Every value must be a plain decimal number: 6000000, never 6e6 or 6M or "6 million". Rates are \
fractions: 0.11, never 11%. Include only levers you want to change; leave out the rest. `{{}}` \
means change nothing.\
"""

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LeverParseFailure(RuntimeError):
    """The advisor's decision could not be read, and the run cannot be honoured.

    Carries everything needed to diagnose it without re-running: the turn, the levers that stayed
    unreadable, and every answer the advisor gave along the way.
    """

    def __init__(self, turn: int, vague: list[str], attempts: list[str]) -> None:
        self.turn = turn
        self.vague = vague
        self.attempts = attempts
        super().__init__(
            f"turn {turn}: could not read a usable value for {', '.join(vague) or 'any lever'} "
            f"after {len(attempts)} attempt(s)"
        )


@dataclass
class ReviewOutcome:
    """What a turn's decision cost to read."""

    levers: dict[str, float] = field(default_factory=dict)
    # How the decision was obtained, for the run report. "contract" is the free, deterministic
    # path; anything else means the advisor did not do as it was asked, which is a finding.
    source: str = "contract"
    clarifications: int = 0
    vague: list[str] = field(default_factory=list)


def _lever_lines() -> str:
    return "\n".join(f"  {n}: {LEVERS[n].minimum} to {LEVERS[n].maximum} ({LEVERS[n].unit})" for n in LEVERS)


def review(llm: Any, answer: str) -> tuple[dict[str, float], list[str]]:
    """Extract levers and vague mentions from an answer that broke the contract.

    Returns `(levers, vague)`. Raises `LeverBlockInvalid` if the reviewer's own reply cannot be
    read as JSON -- deterministic parsing all the way down, or a loud failure.
    """
    from blindcity.agent.llm import user_turn

    reply = llm.generate(
        system=_SYSTEM.format(levers=_lever_lines()),
        history=[user_turn(f"Analyst's recommendation:\n\n{answer}")],
    )
    match = _JSON_OBJECT.search(reply.text or "")
    if not match:
        raise LeverBlockInvalid(f"the reviewer returned no JSON object: {(reply.text or '')[:200]!r}")
    try:
        payload = json.loads(match.group(0))
    except ValueError as exc:
        raise LeverBlockInvalid(f"the reviewer's JSON does not parse: {exc}") from exc

    levers: dict[str, float] = {}
    for name, value in (payload.get("levers") or {}).items():
        if name not in LEVERS or isinstance(value, bool) or not isinstance(value, int | float):
            # The reviewer is held to the same standard as the advisor: a value that is not a
            # number is not an extraction, so it is treated as something still unresolved.
            continue
        levers[name] = LEVERS[name].clamp(float(value))
    vague = [n for n in (payload.get("vague") or []) if n in LEVERS and n not in levers]
    return levers, vague


def read_decision(
    answer: str, *, turn: int, llm: Any, ask_again: Any, record: Any = None
) -> ReviewOutcome:
    """Turn one advisor answer into a lever decision, or abandon the run trying.

    `ask_again(prompt) -> str` puts a follow-up to the advisor in its existing conversation, so a
    clarification arrives with all the context the original answer had. `record`, if given, is
    called with each exchange so clarifications land in the transcript beside everything else.
    """
    outcome = ReviewOutcome()
    attempts = [answer]
    text = answer

    for attempt in range(MAX_CLARIFICATIONS + 1):
        block: dict[str, float] | None = None
        invalid: str | None = None
        try:
            block = extract_lever_block(text)
        except LeverBlockInvalid as exc:
            invalid = str(exc)

        if block is not None:
            # The contract was followed. `{}` is a decision -- change nothing -- and must not be
            # mistaken for an absent answer.
            outcome.levers = block
            outcome.source = "contract" if attempt == 0 else "clarified"
            outcome.clarifications = attempt
            return outcome

        # No block, or a block that says something unusable. Ask a reader that can cope with prose.
        levers, vague = review(llm, text)
        if not vague:
            outcome.levers = levers
            outcome.source = "reviewed" if attempt == 0 else "clarified"
            outcome.clarifications = attempt
            return outcome

        outcome.vague = vague
        if attempt == MAX_CLARIFICATIONS:
            break

        why = f" for {', '.join(vague)}" if vague else (f": {invalid}" if invalid else "")
        prompt = _CLARIFY.format(why=why)
        if record is not None:
            record({"phase": "clarification_request", "turn": turn, "attempt": attempt + 1,
                    "vague": vague, "prompt": prompt})
        text = ask_again(prompt)
        attempts.append(text)
        if record is not None:
            record({"phase": "clarification_response", "turn": turn, "attempt": attempt + 1,
                    "answer": text})

    raise LeverParseFailure(turn, outcome.vague, attempts)
