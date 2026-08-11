"""Ask DataHub's own Analytics Agent what to do, and act on the answer.

The other two modes reason over the warehouse themselves: our controller writes the SQL, reads the
rows, and decides. This one does not. It behaves like a manager with an analyst on staff — it
describes the situation in plain English, asks which levers to move, and acts on what comes back.

That makes it a different question from the other modes. `agent_raw` and `agent_datahub_live` ask
"is a catalogued warehouse worth more to an agent than an uncatalogued one". This asks "is
DataHub's own analytics agent, pointed at the same warehouse, better at governing the city than an
agent we wrote". Ours writes SQL and holds a plan across turns; theirs is a text-to-SQL analyst
grounded in the catalog, with no memory of the city between questions except what we tell it.

The advisor never actuates anything. It returns prose ending in a decision block; the controller
reads the block and applies it, exactly as a person would read an analyst's answer and then pull
the levers themselves. Nothing the advisor says can move a lever the controller did not choose to
move.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from blindcity.catalog.operational import GUIDANCE_PREFIX
from blindcity.levers import LEVERS

# The Analytics Agent answers over SSE and a real analysis runs to tens of seconds. This bounds one
# question, not the run: a question that times out costs that turn's advice, not the mode.
ADVISOR_TIMEOUT_SECONDS = float(240)

DEFAULT_BASE_URL = "http://localhost:8100"

# How many times one question may be re-put after a rate limit. Four is enough to ride out a
# per-minute window; more would mean the provider is refusing for a reason waiting cannot fix.
RATE_LIMIT_ATTEMPTS = 4

# The provider states its own delay in prose, and on a tokens-per-minute limit that number is
# close to useless: it reports when the *rate* recovers, not when enough of the window has rolled
# to fit the next request. A refusal saying "try again in 281ms" was followed by four failures,
# because one advisor question costs ~114,000 tokens against a 200,000/minute ceiling -- 57% of the
# whole minute in a single call, so two questions can never share one window.
#
# So the first retry waits a full window rather than ramping up to one. A ramp from 8 seconds spends
# its three sleeps on 14s, 16s and 32s -- none of which can clear a minute-long window, so all three
# are refused and the turn is lost anyway. That is what happened: a turn asking for 59,141 tokens
# against 187,999 already used was refused four times in 62 seconds and forfeited.
#
# Nothing else is consuming this budget, so one window is a guarantee rather than a guess. The
# ceiling is per wait, not a total: three sleeps of 65-70s, about 3.5 minutes at worst for a turn
# that would otherwise be lost outright.
#
# The ceiling bounds the *ramp*, never the provider's own number. These constants are tuned for a
# per-minute bucket; a refusal citing an hourly or daily one says "try again in 300s", and clamping
# that to 70 would spend all four attempts inside three minutes, be refused every time, and lose
# the turn -- the exact failure this backoff exists to prevent, in a bucket it was not tuned for.
# When the provider names a longer wait than our ramp, the provider is right.
_RATE_LIMIT_DELAY = re.compile(r"try again in ([0-9.]+)\s*(ms|s)", re.IGNORECASE)
_RATE_LIMIT_FLOOR = 65.0
_RATE_LIMIT_CEILING = 70.0


def _rate_limit_delay(exc: Exception, attempt: int = 0) -> float | None:
    """Seconds to wait before re-putting a question, or None if this is not a rate limit."""
    text = str(exc)
    if "rate limit" not in text.lower() and "429" not in text:
        return None
    suggested = 0.0
    match = _RATE_LIMIT_DELAY.search(text)
    if match:
        suggested = float(match.group(1))
        if match.group(2).lower() == "ms":
            suggested /= 1000.0
    return max(suggested, min(_RATE_LIMIT_FLOOR * (2**attempt), _RATE_LIMIT_CEILING))


# The two Analytics Agent tools verified to return `datasetProperties.customProperties`, which is
# where this project's operating guidance is published. `get_entities` selects them in its
# `entityPreview` fragment and `search` in the shared `fragments.gql`; neither is stripped on the way
# back. Every other tool it has -- lineage, schema fields, documents, assertions -- can reach the
# catalog but cannot return a `blindcity.guidance.*` property, so a run that called only those has
# still never seen the guidance.
#
# Their tool names, not ours, so this can drift with their package. All tool calls are counted
# regardless; this set only decides which of them could possibly have carried the guidance.
GUIDANCE_BEARING_TOOLS = frozenset({"get_entities", "search"})


class LLMMismatch(RuntimeError):
    """The advisor is not configured like the modes it is being compared against."""


@dataclass
class Advice:
    """One answer from the advisor, and what it cost."""

    question: str
    answer: str
    seconds: float = 0.0
    error: str | None = None
    queries: list[str] = field(default_factory=list)
    # Every tool call, in order, as `{"name": ..., "error": str | None}`. `queries` records only
    # SQL, so without this there is no way to tell whether the advisor read the catalog or merely
    # could have: the published guidance went unreferenced for twelve turns and nothing in any
    # artifact said whether it had been fetched and ignored or never fetched at all.
    #
    # The error matters as much as the name. A first version recorded names alone and reported 25
    # catalog reads on a run where every one of them failed -- `get_entities` returns null against
    # DataHub Core -- so the metric intended to prove the guidance was read instead concealed that
    # it never had been. A tool call is not a read.
    tools: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer[:4000],
            "seconds": round(self.seconds, 2),
            "error": self.error,
            "queries": self.queries,
            "tools": self.tools,
        }


# Two patterns, and the difference matters. A block the advisor *labelled* `json` is held to it --
# whatever is inside was offered as the decision, so garbage there is a broken contract rather than
# an absent one. An unlabelled fence is only considered when it plainly contains an object, because
# the advisor also emits SQL in fenced blocks and running `json.loads` over a SELECT would turn
# ordinary output into a parse failure.
#
# Non-greedy so several blocks stay separate, and the *last* is taken: an analyst who shows a
# worked example first and the recommendation last is answering with the last one.
_LABELLED_BLOCK = re.compile(r"```json\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_BRACED_BLOCK = re.compile(r"```\s*(\{.*?\})\s*```", re.DOTALL)


class LeverBlockInvalid(ValueError):
    """A JSON block was present but is not a usable set of lever values."""


def extract_lever_block(text: str) -> dict[str, float] | None:
    """The advisor's decision, read from the JSON block the brief asks it to emit.

    This is the primary reader. It is deterministic, it cannot confuse `6e6` with `6`, and it
    cannot read `11%` as `11`, because it never sees a number that was not written as one.

    Three outcomes, and they must stay distinct:

      * a dict -- the levers to change. `{}` is a real decision meaning "change nothing this turn",
        not an absence.
      * `None` -- no block at all. The contract was not followed and a reader that can cope with
        prose has to look at it.
      * `LeverBlockInvalid` -- a block exists but says something unusable.

    Omission carries meaning: a lever absent from the block keeps its current value. That is why
    words are refused rather than interpreted. "moderate" in a value position could mean the
    advisor wants a change it failed to quantify, and guessing which would be us playing the game
    on its behalf.
    """
    matches = _LABELLED_BLOCK.findall(text) or _BRACED_BLOCK.findall(text)
    if not matches:
        return None
    try:
        payload = json.loads(matches[-1].strip())
    except (TypeError, ValueError) as exc:
        raise LeverBlockInvalid(f"the JSON block does not parse: {exc}") from exc
    if not isinstance(payload, dict):
        raise LeverBlockInvalid(f"expected an object, got {type(payload).__name__}")

    out: dict[str, float] = {}
    for name, value in payload.items():
        if name not in LEVERS:
            raise LeverBlockInvalid(f"{name!r} is not one of the eight levers")
        # `bool` is an `int` in Python and `true` is not a lever value in any sense.
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LeverBlockInvalid(
                f"{name} = {value!r} is not a number. Values must be plain decimals; a value the "
                "advisor could not write as a number is not a decision."
            )
        out[name] = LEVERS[name].clamp(float(value))
    return out


class AnalyticsAgentAdvisor:
    """Talks to a running DataHub Analytics Agent over its conversation API."""

    name = "analytics_agent"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        engine: str = "blindcity",
        timeout: float = ADVISOR_TIMEOUT_SECONDS,
    ):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.engine = engine
        self.timeout = timeout
        self.conversation_id: str | None = None
        # Token counts the advisor reports for itself, so this mode's cost is comparable with the
        # others even though we never call the model directly.
        self.tokens = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        # Questions re-put after a rate limit. A turn saved this way is a turn the mode got
        # to play, and one lost is a hole in the run that the score cannot show.
        self.rate_limited = 0

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout)

    def preflight(self, expected_model: str) -> None:
        """Refuse to score this mode unless the advisor runs the model the others run.

        The other three modes cannot diverge on model or reasoning budget -- they share one client
        and a test enforces it. This one is a separate service with its own configuration, so the
        same guarantee has to be checked at runtime instead. A silent mismatch here would produce a
        number that looks comparable and is not.

        Reasoning effort cannot be checked remotely: the service exposes provider, model and
        whether a key is present, but not the budget. It is set through LLM_REASONING_EFFORT in the
        advisor's own environment -- see infra/analytics-agent/README.md.
        """
        with self._client() as client:
            r = client.get(f"{self.base_url}/api/settings/llm")
            r.raise_for_status()
            settings = r.json()
        actual = str(settings.get("model") or "")
        if actual != expected_model:
            raise LLMMismatch(
                f"the Analytics Agent at {self.base_url} is running {actual!r} but the other "
                f"modes run {expected_model!r}; scores would not be comparable"
            )
        if not settings.get("has_key"):
            raise LLMMismatch(f"the Analytics Agent at {self.base_url} has no API key configured")

    def start(self, client: httpx.Client) -> str:
        """One conversation for the whole run, so the analyst accumulates context across turns.

        This is the advisor's only form of memory, and it is the fair one: a manager consulting the
        same analyst all year gets an analyst who remembers the city.
        """
        if self.conversation_id:
            return self.conversation_id
        r = client.post(
            f"{self.base_url}/api/conversations",
            json={"title": "City Sim Agent Benchmark", "engine_name": self.engine},
        )
        r.raise_for_status()
        self.conversation_id = r.json()["id"]
        return self.conversation_id

    def ask(self, question: str) -> Advice:
        """Put one question to the advisor, retrying only what is worth retrying.

        A rate limit is not this mode failing to govern the city, it is the mode being denied its
        turn. The other three modes absorb these inside their own HTTP client with full-jitter
        backoff and lose nothing. The advisor calls a service that raises the error straight
        through, so without this it silently forfeits the turn -- two of twelve went that way on
        the first run with DataHub context attached, because 22 context tools roughly doubled the
        prompt and the late turns are the expensive ones.

        Anything that is not a rate limit is returned as it happened. A bad question, a dead
        service, or an unparseable stream is a real result for this mode and must not be papered
        over by trying again.
        """
        started = time.monotonic()
        # Handed to `_send` so that whatever the advisor called before a stream died is still on
        # record. A turn that fails halfway is the one whose tool calls are most worth having.
        tools: list[dict[str, Any]] = []
        for attempt in range(RATE_LIMIT_ATTEMPTS):
            tools.clear()
            try:
                with self._client() as client:
                    conv = self.start(client)
                    answer, statements = self._send(client, conv, question, tools)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                delay = _rate_limit_delay(exc, attempt)
                if delay is not None and attempt < RATE_LIMIT_ATTEMPTS - 1:
                    self.rate_limited += 1
                    # Jittered, because a retry that lands on the same second as the one that was
                    # refused is not a retry.
                    time.sleep(delay + random.uniform(0.0, 2.0))
                    continue
                return Advice(
                    question=question,
                    answer="",
                    seconds=time.monotonic() - started,
                    error=f"{type(exc).__name__}: {str(exc)[:300]}",
                    tools=list(tools),
                )
            break
        return Advice(
            question=question,
            answer=answer,
            seconds=time.monotonic() - started,
            queries=statements,
            tools=tools,
        )

    def _send(
        self, client: httpx.Client, conv: str, question: str, tools: list[dict[str, Any]]
    ) -> tuple[str, list[str]]:
        """Post the question and read the streamed reply to completion.

        Events arrive as `{"event": KIND, "payload": {...}}`. `TEXT` carries the answer a token at
        a time, `SQL` the statements it ran, `TOOL_RESULT` the name of every tool it called, and
        `USAGE` its token counts -- which are recorded so this mode's cost sits beside the others'
        rather than reading as free.

        `tools` is appended to rather than returned, so a stream that dies partway still leaves the
        caller holding everything the advisor had called up to that point.
        """
        text_parts: list[str] = []
        statements: list[str] = []
        with client.stream(
            "POST",
            f"{self.base_url}/api/conversations/{conv}/messages",
            json={"text": question},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = event.get("event")
                payload = event.get("payload") or {}
                if kind == "TEXT" and isinstance(payload.get("text"), str):
                    text_parts.append(payload["text"])
                elif kind == "SQL":
                    sql = payload.get("sql") or payload.get("query")
                    if isinstance(sql, str):
                        statements.append(sql[:600])
                elif kind == "TOOL_RESULT":
                    name = payload.get("tool_name")
                    if isinstance(name, str) and name:
                        failed = bool(payload.get("is_error"))
                        result = str(payload.get("result", ""))
                        call: dict[str, Any] = {
                            "name": name,
                            "error": result[:300] if failed else None,
                        }
                        # Whether this call actually brought the guidance back. A `search` for the
                        # wrong thing succeeds and returns nothing, and "did not fail" cannot tell
                        # that apart from "returned all eight bands" -- which is the exact run this
                        # metric exists to catch: the advisor searched for the concept, got an empty
                        # result, and reported that the bands could not be verified.
                        if name in GUIDANCE_BEARING_TOOLS and not failed:
                            call["guidance"] = GUIDANCE_PREFIX in result
                        tools.append(call)
                elif kind == "USAGE":
                    for key in self.tokens:
                        self.tokens[key] += int(payload.get(key, 0) or 0)
                elif kind == "ERROR":
                    message = payload.get("error") or payload.get("message")
                    if isinstance(message, str) and message:
                        raise ValueError(message[:300])
        return "".join(text_parts).strip(), statements
