"""The one client every arm talks to: OpenAI's Responses API.

The benchmark's validity rests on its arms being byte-identical apart from one block of context.
So the conversation is held in a **provider-neutral** form and the client serialises it. The
controller never sees a wire format and cannot accidentally send one mode something subtly
different from another.

**OpenAI is the only supported provider.** A local OpenAI-compatible server (LM Studio, vLLM,
Ollama) used to be reachable through a second client speaking `/chat/completions`, and Gemini
through a third. Both are gone. Every published number came from the hosted path, so the others
were routes nothing verified — and an untested route in the one module that decides what the
model sees is a place for the two arms to silently diverge, which is the single failure this
benchmark cannot survive. One provider, one client, one wire format.

The API key is read from the environment. It is never logged, never echoed into a prompt, never
written to a result file, and travels in a header rather than a query string, where it would land
in proxy logs and shell history.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from blindcity import config  # noqa: F401  -- imported for its .env loading side effect

# Every arm must use the same model. That is a fairness requirement, not a preference.
#
# There is deliberately no default model. An unset LLM_MODEL used to fall back to a local model
# name, which then got sent to a hosted API and 404'd; guessing a model id is a failure this
# project has already paid for twice. The base URL is overridable only so an OpenAI-compatible
# gateway can be put in front of the real thing -- it must still speak `/v1/responses`.
DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")

# How long the model may take to answer, in seconds. This is a *thinking budget*, and it is
# deliberately generous: a reasoning model can spend minutes on one reply, and cutting it off
# would not measure the model, it would measure our patience. Every other timeout in this
# project bounds a piece of infrastructure -- a SQL query, a lock, an HTTP fetch of the catalog
# -- and those are tight because they should never be slow. Do not conflate the two: shortening
# this one silently handicaps the thing being benchmarked.
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT", "900"))

# How hard the model is allowed to think per reply, for models that expose a reasoning budget.
#
# Set explicitly rather than left to the provider default, because it is a property of the thing
# being benchmarked and every mode must get the same one. It ran on the unstated default through
# every result up to 2026-08-09 -- roughly 256 output tokens a call, reasoning included, which is
# a model barely thinking.
#
# `low` is deliberate, not thrift. The comparison is about what the *catalog* supplies; a large
# reasoning budget lets the control mode brute-force its way to the same conclusions by querying
# more, which compresses the very difference being measured.
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "low").strip().lower()

# Tokens per minute the provider will accept before it starts refusing. Zero disables pacing.
#
# Reacting to 429s is not enough on a tokens-per-minute limit. The window is a full minute, and a
# run that has already spent its budget will be refused for the rest of it no matter how politely
# it retries -- gpt-4o on a 30,000 TPM org lost the last four turns of a twelve-turn run that way,
# because memory makes late turns the most expensive ones and they arrive after the budget is
# already gone. So the limit is respected before the request rather than discovered after it.
LLM_TOKENS_PER_MINUTE = int(os.environ.get("LLM_TOKENS_PER_MINUTE", "0") or 0)


class LLMError(RuntimeError):
    """The provider refused, failed, or returned something unusable."""


# --- Provider-neutral conversation ------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    # OpenAI matches a tool result to its call by an explicit id. Minting one here keeps the
    # conversation type independent of any particular wire format.
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class ToolResult:
    call: ToolCall
    payload: dict[str, Any]


@dataclass
class Turn:
    """One conversational turn. `model` turns carry calls; `user` turns carry text or results."""

    role: str  # "user" | "model"
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)


@dataclass
class Usage:
    """Token accounting, so a scored run can be budgeted before it is paid for."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    seconds: float = 0.0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        self.calls += other.calls
        self.seconds += other.seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
            "seconds": round(self.seconds, 2),
        }


@dataclass
class Reply:
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class LLM(Protocol):
    """What the controller depends on. Both backends satisfy it."""

    model: str

    def generate(
        self, *, system: str, history: list[Turn], tools: list[dict[str, Any]] | None = None
    ) -> Reply: ...


# --- Shared HTTP behaviour ---------------------------------------------------------------------


class _HttpClient:
    """Retries, pacing, and the one place a request actually leaves the process."""

    def __init__(
        self,
        *,
        timeout: float,
        max_retries: int,
        min_interval: float,
        backoff_base: float = 4.0,
        backoff_cap: float = 90.0,
        tokens_per_minute: int = 0,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        # Pacing exists for hosted per-minute rate limits: firing a turn's tool calls back to
        # back trips them within seconds, and retrying inside the same minute cannot clear it.
        # Local inference has no such limit, so this is 0 there and is pure waiting otherwise.
        self.min_interval = float(os.environ.get("LLM_MIN_INTERVAL", min_interval))
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._last_request = 0.0
        self.usage = Usage()
        self.tokens_per_minute = int(
            os.environ.get("LLM_TOKENS_PER_MINUTE", tokens_per_minute or LLM_TOKENS_PER_MINUTE)
        )
        # (timestamp, tokens) for the last minute of traffic, oldest first.
        self._spend: deque[tuple[float, int]] = deque()
        # How much the next request is assumed to cost, from the largest seen so far. Assuming the
        # largest rather than the average is deliberate: under-estimating means being refused,
        # which costs a whole minute, while over-estimating only costs a short wait.
        self._largest_call = 0
        self.rate_limited = 0
        self.throttled_seconds = 0.0

    def record_spend(self, tokens: int) -> None:
        """Note what a completed call actually cost, for the token budget."""
        if tokens <= 0:
            return
        self._spend.append((time.monotonic(), tokens))
        self._largest_call = max(self._largest_call, tokens)

    def _await_token_budget(self) -> None:
        """Wait until the next call is expected to fit inside the per-minute allowance."""
        if self.tokens_per_minute <= 0:
            return
        for _ in range(120):  # bounded so a mis-set budget cannot hang a run forever
            now = time.monotonic()
            while self._spend and now - self._spend[0][0] >= 60.0:
                self._spend.popleft()
            spent = sum(tokens for _, tokens in self._spend)
            if spent + self._largest_call <= self.tokens_per_minute or not self._spend:
                return
            # Sleep until the oldest call falls out of the window, which is the soonest the
            # budget can free up.
            wait = max(0.1, 60.0 - (now - self._spend[0][0]) + 0.25)
            self.throttled_seconds += wait
            time.sleep(wait)

    def _pace(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _retry_after(payload: dict[str, Any], headers: Any = None) -> float | None:
        """Providers that state their own backoff are believed in preference to a guess.

        Three formats, because the two providers state it three different ways and reading only
        one of them means every OpenAI 429 fell through to a blind guess:

          * the `Retry-After` header, which is standard and authoritative
          * a nested `error.details[].retryDelay`
          * OpenAI's prose -- "Please try again in 1.007s" -- which is the only place the number
            appears on some responses
        """
        if headers is not None:
            raw = headers.get("retry-after") or headers.get("Retry-After")
            if raw:
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    pass
        for detail in (payload.get("error") or {}).get("details") or []:
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                try:
                    return float(delay[:-1])
                except ValueError:
                    continue
        message = (payload.get("error") or {}).get("message")
        if isinstance(message, str):
            match = re.search(r"try again in ([0-9.]+)\s*(ms|s)", message)
            if match:
                value = float(match.group(1))
                return value / 1000.0 if match.group(2) == "ms" else value
        return None

    def _backoff(self, attempt: int, suggested: float | None) -> float:
        """Exponential backoff with full jitter, capped.

        Jitter matters more than it looks. Both benchmark modes hammer the same endpoint, and a
        turn fires several tool calls in quick succession; without randomisation, everything that
        gets rate-limited together retries together, and the same collision repeats on every
        attempt. Full jitter (uniform over the whole window) spreads them out.

        A provider that states its own delay is believed, but still jittered a little so
        simultaneous callers do not line back up.
        """
        if suggested:
            return suggested + random.uniform(0.0, min(2.0, suggested * 0.25))
        window = min(self.backoff_cap, self.backoff_base * (2**attempt))
        return random.uniform(0.0, window)

    def post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._await_token_budget()
            self._pace()
            sleep_for: float | None = None
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(url, json=body, headers=headers)
                self._last_request = time.monotonic()
                if r.status_code == 200:
                    return r.json()
                # 429 and 5xx are worth another go. Any other 4xx is our bug, and retrying only
                # burns quota against the same broken request.
                if r.status_code != 429 and r.status_code < 500:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                last = LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                if r.status_code == 429:
                    self.rate_limited += 1
                    try:
                        sleep_for = self._retry_after(r.json(), r.headers)
                    except ValueError:
                        sleep_for = self._retry_after({}, r.headers)
                    # A tokens-per-minute refusal clears when the window rolls, so a delay the
                    # provider suggests can be far shorter than the wait actually required.
                    if self.tokens_per_minute > 0:
                        sleep_for = max(sleep_for or 0.0, 5.0)
            except httpx.HTTPError as exc:
                last = exc
                self._last_request = time.monotonic()
            if attempt < self.max_retries - 1:
                time.sleep(self._backoff(attempt, sleep_for))
        raise LLMError(f"request failed after {self.max_retries} attempts: {last}")


# --- Hosted OpenAI, Responses API --------------------------------------------------------------


class ResponsesClient(_HttpClient):
    """OpenAI's `/v1/responses`.

    Reasoning models refuse function tools on `/chat/completions` unless reasoning is switched
    off — `gpt-5.6-luna` says so in the error. Since diagnosing a failing city from its data is
    precisely the reasoning being measured, disabling it to keep the simpler endpoint would
    hollow out the benchmark. This endpoint gives tools and reasoning together.

    Stateless on purpose: the conversation is resent each call rather than chained with
    `previous_response_id`. Every turn already starts fresh, both other backends work that way,
    and server-side state is one more thing that could quietly differ between the two modes.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str | None = None,
        temperature: float | None = None,
        timeout: float = LLM_TIMEOUT_SECONDS,
        max_retries: int = 4,
        min_interval: float = 0.0,
        api_key: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        super().__init__(timeout=timeout, max_retries=max_retries, min_interval=min_interval)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        resolved = (model or os.environ.get("LLM_MODEL") or "").strip()
        if not resolved:
            raise LLMError(
                "LLM_MODEL is not set. Set it to a model id the provider actually serves — list "
                "them rather than guessing. Both modes must use the same one."
            )
        self.model = resolved
        # Reasoning models reject a non-default temperature outright, so it is not sent at all.
        self.temperature = temperature
        self.reasoning_effort = (reasoning_effort or LLM_REASONING_EFFORT) or None
        # Only reasoning models accept a reasoning budget; gpt-4o rejects the parameter outright.
        # Rather than keep a list of which models are which -- a list that is wrong the moment a
        # model is released -- the first refusal turns it off for the rest of the run. One client
        # is shared by every mode, so this flips for all of them at once and cannot become a
        # difference between them. `reasoning_sent` records what actually happened, because "the
        # budget was set to low" and "the budget was silently dropped" must not look alike in a
        # report.
        self._send_reasoning = bool(self.reasoning_effort)
        self.reasoning_sent: bool | None = None
        self._key = (
            api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        )
        if not self._key:
            raise LLMError("LLM_API_KEY is not set. Put it in .env, never on the command line.")

    @staticmethod
    def _tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Responses takes flat function tools, without the `{type, function: {...}}` nesting
        that `/chat/completions` requires."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {}),
            }
            for t in tools
        ]

    @staticmethod
    def _input(history: list[Turn]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for turn in history:
            if turn.role == "model":
                if turn.text:
                    items.append(
                        {"role": "assistant", "content": [{"type": "output_text", "text": turn.text}]}
                    )
                items.extend(
                    {
                        "type": "function_call",
                        "call_id": c.id,
                        "name": c.name,
                        "arguments": json.dumps(c.args),
                    }
                    for c in turn.calls
                )
            elif turn.results:
                # Matched back to the call by `call_id`; the payload travels as a JSON string.
                items.extend(
                    {
                        "type": "function_call_output",
                        "call_id": r.call.id,
                        "output": json.dumps(r.payload),
                    }
                    for r in turn.results
                )
            else:
                items.append(
                    {"role": "user", "content": [{"type": "input_text", "text": turn.text}]}
                )
        return items

    def generate(
        self, *, system: str, history: list[Turn], tools: list[dict[str, Any]] | None = None
    ) -> Reply:
        body: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": self._input(history),
        }
        converted = self._tools(tools)
        if converted:
            body["tools"] = converted
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self._send_reasoning:
            body["reasoning"] = {"effort": self.reasoning_effort}

        url = f"{self.base_url}/responses"
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        started = time.monotonic()
        try:
            data = self.post(url, body, headers)
        except LLMError as exc:
            if self._send_reasoning and "reasoning" in str(exc).lower():
                self._send_reasoning = False
                body.pop("reasoning", None)
                data = self.post(url, body, headers)
            else:
                raise
        self.reasoning_sent = self._send_reasoning
        elapsed = time.monotonic() - started

        raw_usage = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(raw_usage.get("input_tokens", 0)),
            output_tokens=int(raw_usage.get("output_tokens", 0)),
            total_tokens=int(raw_usage.get("total_tokens", 0)),
            calls=1,
            seconds=elapsed,
        )
        self.usage.add(usage)

        text_chunks: list[str] = []
        calls: list[ToolCall] = []
        for item in data.get("output") or []:
            kind = item.get("type")
            if kind == "function_call":
                arguments = item.get("arguments") or "{}"
                try:
                    args = json.loads(arguments)
                except json.JSONDecodeError:
                    # Surfaced as a tool error so the model can see and correct it, rather than
                    # killing the turn outright.
                    args = {"__malformed_arguments__": str(arguments)[:500]}
                calls.append(
                    ToolCall(name=item.get("name", ""), args=args, id=str(item.get("call_id") or ""))
                )
            elif kind == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text" and part.get("text"):
                        text_chunks.append(part["text"])
            # `reasoning` items carry no user-visible text and are deliberately not replayed.

        return Reply(text="".join(text_chunks).strip(), calls=calls, usage=usage)


# --- Selection ----------------------------------------------------------------------------------


def build_llm(model: str | None = None) -> LLM:
    """Construct the one client every mode uses.

    A factory with a single branch looks like a candidate for inlining, and it is kept anyway: it
    is the seam that makes "every mode is on the same model" a structural fact rather than a
    convention. Every arm calls this, so none of them can end up somewhere else.
    """
    return ResponsesClient(model)


def user_turn(text: str) -> Turn:
    return Turn(role="user", text=text)
