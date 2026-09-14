"""A controller that governs by asking DataHub's Analytics Agent, rather than by querying itself.

This is the manager-with-an-analyst shape. Each turn it states the situation in plain English —
which levers are in force, how many turns remain, what it changed last time — asks which levers to
move, and applies whatever lever values come back. It writes no SQL and holds no view of the city
of its own.

Two things it deliberately does *not* do, because either would turn the mode into a measurement of
our scaffolding instead of the advisor:

  * It does not tell the advisor anything about the city's state. Not the population, not the
    treasury, not a single reading. The advisor is connected to the same warehouse and the same
    catalog; finding out what is wrong is its job, and handing it a briefing would measure how
    well we summarise rather than how well it analyses.
  * It does not second-guess the answer. If the advice names no lever, the turn passes with no
    change. A controller that fell back to a policy of its own would be scoring that policy.

Three things it *does* say, each of which the other three modes are told and this one was not.
Withholding them was not neutrality, it was a handicap, and it showed up in the score:

  * **The objective.** With no goal stated, the advisor optimised for prudent municipal finance --
    the highest solvency of any mode and the lowest satisfaction. It raised prices to fund the
    capex it had correctly diagnosed, and the residents left. Nothing in its brief said that was
    the wrong trade.
  * **An instruction to look again.** Every turn the other modes are told to investigate. The
    advisor was told only that time had passed, so after turn 0 it answered from memory: one query
    per turn against 65 for `agent_raw`, on a city that had moved underneath it.
  * **What its last recommendation became.** The other modes open every turn with the result of
    their last decision, including anything clamped. Every figure restated here is one the advisor
    itself produced, so this is parity rather than a hint.

And one thing it is told that no other mode needs to be: **where the expert guidance lives.**
`agent_datahub_live` has the bands and the response lags rendered into its prompt by us. This mode
is given an address instead -- the datasets, the property prefix, the tool -- and has to fetch the
guidance itself through DataHub's own tools. That is a harder test, not an easier one, and it is
the only version of the claim worth making: the bytes it reasons from came out of DataHub, fetched
by DataHub's agent, with no band of ours anywhere in the question. See `CATALOG` for what the
alternatives measured.

**On the output contract and the clarification rounds.** This mode is asked to end every answer
with a JSON block, and when it does not, `lever_review` reads the answer and may ask up to three
times for a usable number before the run is abandoned. That looks like an allowance the other modes
do not get. It is the opposite:

  * They call `set_levers` with a **JSON schema that makes vagueness impossible** -- the tool will
    not accept "a moderate level".
  * When they emit malformed arguments they get a tool error back and **retry inside the same
    turn**.

The advisor has neither, because it answers in prose into a service we do not control. A
clarification round is the prose equivalent of the tool error the others get for free. Without it,
this mode alone would be scored on whether our reader happened to understand its formatting -- and
it once was: `road_maintenance_budget = 2e6` was read as `2`, and the mode spent three turns
leaving the roads unfunded because of it.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from blindcity.agent.advisor import GUIDANCE_BEARING_TOOLS, Advice, AnalyticsAgentAdvisor
from blindcity.agent.lever_review import read_decision
from blindcity.levers import LEVERS
from blindcity.sim.model import CityState

# The objective, in the words the other three modes are given. Its absence was not neutral: with
# no goal stated, the advisor optimised for prudent municipal finance -- which is a perfectly good
# thing for an analyst to do, and produced the highest solvency of any mode (0.845) and the lowest
# satisfaction (0.575). It raised prices to fund the capex it correctly identified, and the
# residents left. Nothing in its brief said that was the wrong trade.
OBJECTIVE = """\
The city is in crisis. The manager's job is to get it healthy again within a limited number of \
turns. A healthy city is solvent, its residents are satisfied and staying, its services meet \
demand, and its population is stable or growing -- all four at once, not one bought with another.\
"""

BRIEF = """\
You are advising the manager of a city. {objective}

The city's operational data is in the warehouse you are connected to, catalogued in DataHub: one \
row per entity per simulated month, covering citizens, buildings, roads, power, water, the \
municipal budget, and the policy levers in force each month.

The manager controls exactly eight levers and nothing else:

{levers}

{catalog}

Investigate the data and tell the manager which levers to change and to what values. Explain your \
reasoning in prose, then end your answer with the decision block described below.

{contract}\
"""

# Where the expert guidance lives, and how to fetch it. An address, never a value: every band and
# every note stays in DataHub, and this paragraph is assembled from the same constants that
# published them, so it cannot drift into quoting one.
#
# It names the datasets and the one tool that works rather than inviting a search, and both halves
# of that were measured rather than argued. Probed on 2026-08-11 with turn-0 questions:
#
#   * told nothing, the advisor called `search_documents`, found nothing, and went straight to the
#     warehouse. No catalog read on any of its eleven tool calls -- which is what the recorded
#     twelve-turn run did too, and why the published guidance went unreferenced.
#   * told only that the catalog carries operating guidance, it searched for the *concept* --
#     "operating guidance", "lever bands" -- and reported back: "The catalog search returned no
#     operating guidance ... so the recommended bands and response times could not be verified."
#     `search` matches names and descriptions, not custom property values, so a concept query
#     cannot find them. It then set `property_tax_rate` to 0.015, nearly twice the documented
#     ceiling: it had looked, found nothing, and proceeded with more confidence than it had earned.
#   * told to call `get_entities` on the six URNs, it did, twenty-five times across twelve turns,
#     and every single call returned null. `get_entities` sends a 42KB query selecting fields that
#     exist only in DataHub Cloud (`DataFlow.documentation`, `DatasetStatsSummary.rowCount`, and
#     nine more), so against DataHub Core the whole query fails validation and no data comes back.
#     The run scored 0.7527 having never once read the guidance, and said so in its own prose.
#
# `search` by dataset *name* is the path that works: one call returns `lever_monthly` with all
# eight `{prefix}.lever.*` properties attached. That is why the instruction names the tool.
CATALOG = """\
The warehouse is catalogued in DataHub, and the catalog carries expert-authored operating guidance \
for exactly these levers, published as custom properties under the key prefix `{prefix}.` on these \
datasets:

{names}

`{prefix}.lever.*` gives the band each lever should sit in and how much moving it is worth at all; \
`{prefix}.outcome.*` gives the healthy range for each outcome; `{prefix}.lag.*` gives how many \
months each system takes to respond to a change. None of it is in any table -- every lever is \
constant across the whole recorded history, so no query can reveal it.

Read it with the `search` tool, one dataset name at a time -- `search` returns each matching \
dataset with its custom properties attached, and searching for the dataset name is what finds \
them. Searching for the guidance itself will not: the catalog indexes names and descriptions, not \
property values. Do not use `get_entities` for this; it fails against this DataHub.

Start with `{lever_table}`, which carries the band for all eight levers, and read it before your \
first recommendation.\
"""


def catalog_pointer() -> str:
    """The `CATALOG` paragraph, addressed at the datasets that actually carry guidance."""
    from blindcity.catalog.operational import (
        GUIDANCE_PREFIX,
        LEVER_GUIDANCE_TABLE,
        guidance_properties,
    )

    names = "\n".join(f"  {table}" for table in sorted(guidance_properties()))
    return CATALOG.format(
        prefix=GUIDANCE_PREFIX, names=names, lever_table=LEVER_GUIDANCE_TABLE
    )

# The output contract, restated on every turn. It is repeated rather than stated once at the start
# because it is the one part of the brief that must survive twelve turns of accumulated context --
# and because a single misread value is not a worse answer, it is a different experiment.
#
# Each rule is here because the free-text parser it replaces got that exact case wrong: `6e6` read
# as 6, `6M` read as 6, and `11%` read as 11 and then clamped to the legal maximum, which looks
# deliberate in a result file. That parser is gone; see docs/ERRORS.md for what it cost.
CONTRACT = """\
End your answer with a fenced JSON block and nothing after it:

```json
{"income_tax_rate": 0.11, "road_maintenance_budget": 6000000}
```

The block is the decision. The prose above it is only your reasoning. Rules, all of them strict:

  * Include ONLY the levers you want to change. A lever you leave out keeps its current value --
    that is how you say "leave this one alone". Do not name a lever you are not changing.
  * `{}` is a valid answer. It means change nothing this turn.
  * Every value must be a plain decimal number: `6000000`. Never `6e6`, never `6M`, never
    `6 million`, never `6,000,000`.
  * Rates are fractions, never percentages: `0.11`, never `11%` and never `11`.
  * No words, no ranges, no nulls, no comments. "moderate", "high", "3-5 million" and `null` are
    all rejected. A value you cannot write as a single number is not a decision.

If the block is missing or a value is not a number, you will be asked again, and a run that still
cannot be read after three attempts is abandoned.\
"""


@dataclass
class AdvisorController:
    """A `Controller` that delegates the analysis to the Analytics Agent."""

    name: str
    advisor: AnalyticsAgentAdvisor
    # Used only to read an answer that broke the output contract -- never to decide anything. It
    # is the same client and model every other mode runs on, because it is infrastructure like the
    # SQL tool rather than a player: see `lever_review`.
    llm: Any = None
    turn_budget: int | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    # Where to record every exchange. The other modes get this from `RecordingLLM`, which wraps
    # the LLM client; this one calls no client, so it writes its own -- same file name, same JSONL
    # shape, so an auditor does not need to know which mode produced which artifact.
    transcript: str | None = None
    # Tools the advisor called while answering this turn's clarifications, collected by
    # `_ask_again` and folded into the turn record beside the ones from the original answer.
    _clarification_tools: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.transcript:
            path = Path(self.transcript)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Truncate, so a rerun cannot be read as one long run.
            path.write_text("", encoding="utf-8")

    def _record(self, record: dict[str, Any]) -> None:
        if not self.transcript:
            return
        with Path(self.transcript).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _question(self, state: CityState, turn: int) -> str:
        levers = "\n".join(
            f"  {name}: {LEVERS[name].minimum} to {LEVERS[name].maximum} ({LEVERS[name].unit}) "
            f"- {LEVERS[name].description}"
            for name in LEVERS
        )
        current = "\n".join(f"  {n}: {state.levers.get(n, LEVERS[n].default):g}" for n in LEVERS)

        if turn == 0:
            head = BRIEF.format(
                levers=levers,
                objective=OBJECTIVE,
                catalog=catalog_pointer(),
                contract=CONTRACT,
            )
        else:
            # After the first turn the advisor has the conversation; restating the brief each time
            # would crowd its own accumulated context. What must be restated is the instruction to
            # go and look again. Without it the advisor answered from what it remembered: after
            # turn 0 it ran a single query per turn, against 65 for `agent_raw`, and its later
            # recommendations drifted on memory of a city three, six, nine months out of date.
            head = (
                "Three months have passed since your last recommendation and the city has moved. "
                "Query the warehouse again before answering -- the earlier figures are stale. "
                # One line, not the whole paragraph: the URNs are in the conversation from turn 0.
                # What fades over twelve turns is the habit of consulting the guidance at all, and
                # the bands are what keep the later turns from drifting outside them.
                "The catalog guidance you read at the start still applies; check a band there "
                "before moving a lever rather than estimating one.\n\n"
                # The contract is repeated every turn rather than trusted to survive from turn 0.
                # It is the one instruction whose failure is not a worse answer but an unreadable
                # one, and twelve turns of accumulated context is a long way from where it was said.
                + CONTRACT
            )

        remaining = ""
        if self.turn_budget is not None:
            left = self.turn_budget - turn
            remaining = (
                f" This is decision {turn + 1} of {self.turn_budget}; "
                f"{left} remain including this one."
            )

        # What last turn's advice actually became. The other three modes are each told this at the
        # top of every turn ("Result of your last decision:"), and the advisor was not -- so it
        # could not tell a value the manager applied from one clamped to a legal range, or from
        # one it named and the parser never found. Restating it is parity, not a hint: every
        # figure here is one the advisor itself produced.
        confirmation = ""
        if turn > 0 and self.history:
            asked = self.history[-1].get("levers") or {}
            if asked:
                changed = {k: v for k, v in asked.items() if state.levers.get(k) != v}
                lines = ["Result of your last recommendation:"]
                lines.append(
                    "  in force now: " + ", ".join(f"{k}={state.levers[k]:g}" for k in sorted(asked))
                )
                for name in sorted(changed):
                    lines.append(
                        f"  {name}: you asked for {asked[name]:g}, in force is "
                        f"{state.levers.get(name, float('nan')):g} (clamped to its legal range)"
                    )
                confirmation = "\n".join(lines) + "\n\n"
            else:
                confirmation = (
                    "Your last answer named no lever value the manager could apply, so nothing "
                    "changed. Give a number for every lever you want moved.\n\n"
                )

        return (
            f"{head}\n\n"
            f"{confirmation}"
            f"Levers currently in force:\n{current}\n\n"
            f"Which levers should the manager change now, and to what values?{remaining}"
        )

    def decide(self, state: CityState, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        started = time.monotonic()
        question = self._question(state, turn)
        # Written before the call, so a hang or a crash still leaves evidence of what was asked.
        self._record({"mode": self.name, "call": turn + 1, "phase": "request", "question": question})
        advice: Advice = self.advisor.ask(question)
        self._record(
            {
                "mode": self.name,
                "call": turn + 1,
                "phase": "response",
                "answer": advice.answer,
                "queries": advice.queries,
                "tools": advice.tools,
                "error": advice.error,
                "seconds": round(advice.seconds, 2),
            }
        )
        # A turn the advisor never answered is a lost turn, not an unreadable one. There is no
        # text to parse and nothing to clarify, so it passes with no change exactly as before.
        #
        # `levers` is seeded here rather than only on the path that produces one, because every
        # record must have the same shape: `report()` reads `t["levers"]` across the whole history,
        # and a lost turn that omitted the key crashed the run at the end -- destroying eleven
        # good turns over the one that was already lost.
        record = {
            "turn": turn,
            **advice.to_dict(),
            "levers": {},
            "seconds": round(time.monotonic() - started, 2),
        }
        if advice.error:
            self.history.append(record)
            return {}

        self._clarification_tools = []
        outcome = read_decision(
            advice.answer,
            turn=turn,
            llm=self.llm,
            ask_again=self._ask_again,
            record=lambda entry: self._record({"mode": self.name, **entry}),
        )
        # A clarification is another question to the same advisor, so whatever it called while
        # answering one belongs to this turn. Dropping them under-reported exactly the turns that
        # went wrong -- including a `search` that only fetched the guidance on the second ask.
        record["tools"] = [*advice.tools, *self._clarification_tools]
        # The decision is what the block said. There is no second reading to compare it against:
        # the prose regex that used to run beside it was deleted once the contract made it inert.
        record["levers"] = outcome.levers
        record["parse"] = {
            "source": outcome.source,
            "clarifications": outcome.clarifications,
            "vague": outcome.vague,
        }
        self.history.append(record)
        return dict(outcome.levers)

    def _ask_again(self, prompt: str) -> str:
        """Put a follow-up to the advisor inside its existing conversation.

        The same session, so the clarification arrives with everything the original answer had --
        the city it just queried, its own reasoning, and the turn it is answering for.
        """
        advice = self.advisor.ask(prompt)
        self._clarification_tools.extend(advice.tools)
        return advice.answer

    def report(self) -> dict[str, Any]:
        answered = [t for t in self.history if not t["error"]]
        acted = [t for t in self.history if t["levers"]]
        parses = [t["parse"] for t in self.history if t.get("parse")]
        calls = Counter(c["name"] for t in self.history for c in t.get("tools", ()))
        failed = Counter(
            c["name"] for t in self.history for c in t.get("tools", ()) if c.get("error")
        )

        def looked(turn: dict[str, Any]) -> int:
            """Calls on this turn that could have carried guidance and did not fail."""
            return sum(
                1
                for c in turn.get("tools", ())
                if c["name"] in GUIDANCE_BEARING_TOOLS and not c.get("error")
            )

        def read_guidance(turn: dict[str, Any]) -> int:
            """Calls that actually brought a `blindcity.guidance.*` property back.

            Separate from `looked` because the difference is a real and observed outcome: a
            `search` for the wrong term succeeds, returns nothing, and leaves the advisor deciding
            without the bands while every "did it call the tool" measure reads green.
            """
            return sum(1 for c in turn.get("tools", ()) if c.get("guidance"))

        return {
            "controller": self.name,
            "model": f"analytics-agent@{self.advisor.base_url}",
            "catalog": "analytics_agent",
            "monitor": "none",
            "turns": self.history,
            # An advisor that answers and names no lever is a different failure from one that
            # never answered, and the mode's score cannot be read without knowing which happened.
            "answered_turns": len(answered),
            "acting_turns": len(acted),
            "advisor_errors": [t["error"] for t in self.history if t["error"]],
            # How each decision was read. This is a result, not plumbing: a third-party agent that
            # needs clarifying on a third of its turns is telling you something about using it,
            # and until now that was invisible in every artifact the run produced.
            "parsing": {
                "on_contract": sum(1 for p in parses if p["source"] == "contract"),
                "needed_reviewer": sum(1 for p in parses if p["source"] == "reviewed"),
                "needed_clarifying": sum(1 for p in parses if p["source"] == "clarified"),
                "clarification_rounds": sum(p["clarifications"] for p in parses),
                "vague_levers": sorted({v for p in parses for v in p["vague"]}),
            },
            # What the advisor actually called, and on how many turns it *successfully* read
            # metadata that could have carried the published guidance. Three separate claims --
            # "we published it", "the agent asked for it", "the agent got it" -- and a run has
            # already been observed where the first two held and the third did not, on all twelve
            # turns, while the summary line said 25 catalog reads.
            "tool_calls": dict(calls.most_common()),
            # Deliberately not `tool_failures`: the other modes report that as an integer and
            # `_print_diagnostics` does arithmetic on it.
            "failed_tool_calls": dict(failed.most_common()),
            # Looked / got it, kept apart. A high `lookups` beside a zero `reads` is the mode
            # searching the catalog and coming back empty-handed, which is a different diagnosis
            # from never having searched and needs a different fix.
            "guidance_lookups": sum(looked(t) for t in self.history),
            "guidance_reads": sum(read_guidance(t) for t in self.history),
            "turns_reading_guidance": sum(1 for t in self.history if read_guidance(t)),
            # Questions re-put after a 429. A turn saved this way is a turn the mode got to play,
            # and one lost is a hole the score cannot show -- but until now neither was in any
            # artifact, so "the retry works" was an assertion about the code rather than a
            # measurement. A run with retries and no advisor error means the backoff earned its
            # wait; retries alongside a lost turn mean it is still too short.
            "rate_limited": self.advisor.rate_limited,
            # Tokens are the advisor's own, reported back over its stream. We never call the
            # model here, but the mode is not free and must not read as though it were.
            "usage": {
                "prompt_tokens": self.advisor.tokens["input_tokens"],
                "output_tokens": self.advisor.tokens["output_tokens"],
                "total_tokens": self.advisor.tokens["total_tokens"],
                "calls": len(self.history),
                "seconds": round(sum(t["seconds"] for t in self.history), 2),
            },
        }
