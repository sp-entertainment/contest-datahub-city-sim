"""LLM clients behind one interface: hosted Gemini, or a local OpenAI-compatible server.

Two things drove the shape of this module.

First, the benchmark's validity rests on `agent_datahub` and `agent_raw` being byte-identical
apart from one block of context. So the conversation is held in a **provider-neutral** form and
each client serialises it. The controller never sees a wire format and cannot accidentally send
one mode something subtly different from the other.

Second, the hosted path turned out to be unusable on a free-tier key: a scored run is roughly 216
calls per mode, and the daily quota dies long before that (see `.tasks/mvp/SLICE6-HANDOFF.md`).
Local inference removes the quota, the cost, and the network — and lets a judge reproduce the
whole benchmark from a clone, which is a stronger claim than asking them to trust our numbers.

An API key, where one is used at all, is read from the environment. It is never logged, never
echoed into a prompt, never written to a result file, and travels in a header rather than a query
string, where it would land in proxy logs and shell history.
"""

from __future__ import annotations

import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from blindcity import config  # noqa: F401  -- imported for its .env loading side effect

GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

# Both modes must use the same model. That is a fairness requirement, not a preference.
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "local")
DEFAULT_LOCAL_MODEL = os.environ.get("LLM_MODEL") or "qwen/qwen3.6-35b-a3b"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")

# How long the model may take to answer, in seconds. This is a *thinking budget*, and it is
# deliberately generous: a reasoning model can spend minutes on one reply, and cutting it off
# would not measure the model, it would measure our patience. Every other timeout in this
# project bounds a piece of infrastructure -- a SQL query, a lock, an HTTP fetch of the catalog
# -- and those are tight because they should never be slow. Do not conflate the two: shortening
# this one silently handicaps the thing being benchmarked.
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT", "900"))


class LLMError(RuntimeError):
    """The provider refused, failed, or returned something unusable."""


# --- Provider-neutral conversation ------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    # Gemini matches tool results to calls by name; OpenAI needs an explicit id. Minting one
    # here keeps both backends fed from the same structure.
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

    def _pace(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _retry_after(payload: dict[str, Any]) -> float | None:
        """Providers that state their own backoff are believed in preference to a guess."""
        for detail in (payload.get("error") or {}).get("details") or []:
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                try:
                    return float(delay[:-1])
                except ValueError:
                    continue
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
                    try:
                        sleep_for = self._retry_after(r.json())
                    except ValueError:
                        sleep_for = None
            except httpx.HTTPError as exc:
                last = exc
                self._last_request = time.monotonic()
            if attempt < self.max_retries - 1:
                time.sleep(self._backoff(attempt, sleep_for))
        raise LLMError(f"request failed after {self.max_retries} attempts: {last}")


# --- Local, OpenAI-compatible (LM Studio, llama.cpp, vLLM, Ollama) ------------------------------


class OpenAIClient(_HttpClient):
    """Talks to any OpenAI-compatible `/chat/completions` endpoint.

    Covers both the hosted OpenAI API and a local server (LM Studio, llama.cpp, vLLM, Ollama).
    They differ only in `LLM_BASE_URL` and whether the key is real, so one client serves both and
    the benchmark cannot accidentally behave differently depending on where inference happens.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str | None = None,
        temperature: float = 0.0,
        # See LLM_TIMEOUT_SECONDS: a thinking budget, not an infrastructure limit. A large
        # context on a partially-offloaded MoE can take minutes just to prefill, and a timeout
        # here would be scored as the mode failing to steer the city.
        timeout: float = LLM_TIMEOUT_SECONDS,
        max_retries: int = 3,
        min_interval: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        super().__init__(timeout=timeout, max_retries=max_retries, min_interval=min_interval)
        # An unset LLM_MODEL used to fall back to a local model name, which would then be sent
        # to a hosted API and 404. Silently guessing a model id is exactly the failure this
        # project has already paid for twice, so a hosted endpoint demands an explicit one.
        resolved = (model or os.environ.get("LLM_MODEL") or "").strip()
        base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        if not resolved:
            if "localhost" in base or "127.0.0.1" in base:
                resolved = DEFAULT_LOCAL_MODEL
            else:
                raise LLMError(
                    f"LLM_MODEL is not set and {base} is not a local server. Set LLM_MODEL to a "
                    "model id the provider actually serves -- list them first rather than "
                    "guessing; both modes must use the same one."
                )
        self.model = resolved
        self.base_url = base
        self.temperature = temperature
        # Local servers ignore the key entirely; the hosted API does not. OPENAI_API_KEY is
        # accepted as a fallback because that is the name the provider's own tooling uses.
        self._key = (
            api_key
            or os.environ.get("LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or "not-needed"
        )
        # Some newer hosted models accept only the default temperature and 400 on anything else.
        # Detected from the error rather than from a model-name list, which would rot.
        self._send_temperature = True

    @staticmethod
    def _tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [{"type": "function", "function": t} for t in tools]

    @staticmethod
    def _messages(system: str, history: list[Turn]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for turn in history:
            if turn.role == "model":
                message: dict[str, Any] = {"role": "assistant", "content": turn.text or None}
                if turn.calls:
                    message["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.args)},
                        }
                        for c in turn.calls
                    ]
                messages.append(message)
            elif turn.results:
                # OpenAI wants one message per result, keyed back to the call id.
                messages.extend(
                    {
                        "role": "tool",
                        "tool_call_id": r.call.id,
                        "name": r.call.name,
                        "content": json.dumps(r.payload),
                    }
                    for r in turn.results
                )
            else:
                messages.append({"role": "user", "content": turn.text})
        return messages

    def generate(
        self, *, system: str, history: list[Turn], tools: list[dict[str, Any]] | None = None
    ) -> Reply:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(system, history),
        }
        if self._send_temperature:
            body["temperature"] = self.temperature
        converted = self._tools(tools)
        if converted:
            body["tools"] = converted

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        started = time.monotonic()
        try:
            data = self.post(url, body, headers)
        except LLMError as exc:
            # Retry once without temperature if that is what it objected to. Both modes share the
            # client, so this flips for both at once and cannot become a difference between them.
            if self._send_temperature and "temperature" in str(exc).lower():
                self._send_temperature = False
                body.pop("temperature", None)
                data = self.post(url, body, headers)
            else:
                raise
        elapsed = time.monotonic() - started

        raw_usage = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
            output_tokens=int(raw_usage.get("completion_tokens", 0)),
            total_tokens=int(raw_usage.get("total_tokens", 0)),
            calls=1,
            seconds=elapsed,
        )
        self.usage.add(usage)

        choices = data.get("choices") or []
        if not choices:
            raise LLMError("model returned no choices")
        message = choices[0].get("message") or {}

        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function") or {}
            arguments = fn.get("arguments")
            if isinstance(arguments, str):
                try:
                    args = json.loads(arguments or "{}")
                except json.JSONDecodeError:
                    # A small model can emit malformed JSON. Surfacing it as a tool error lets
                    # the model see the problem and retry, rather than killing the turn.
                    args = {"__malformed_arguments__": arguments[:500]}
            else:
                args = dict(arguments or {})
            calls.append(
                ToolCall(name=fn.get("name", ""), args=args, id=str(raw.get("id") or uuid.uuid4().hex[:12]))
            )

        return Reply(text=(message.get("content") or "").strip(), calls=calls, usage=usage)


# `local` and `openai-chat` are the same client pointed at different hosts. The alias keeps the
# name that reads correctly at each call site.
LocalClient = OpenAIClient


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

        started = time.monotonic()
        data = self.post(
            f"{self.base_url}/responses",
            body,
            {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
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


# --- Hosted Gemini ------------------------------------------------------------------------------


class GeminiClient(_HttpClient):
    """Google Generative Language API.

    Availability has moved under this project twice: `gemini-2.5-flash` now 404s for new keys
    while still appearing in the models listing, and `pro` models 429 without billing. Re-check
    before trusting a model name here.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        temperature: float = 0.0,
        # Was 90s, which would have cut a reasoning model off mid-thought. Thinking time is not
        # an infrastructure concern and is not bounded like one.
        timeout: float = LLM_TIMEOUT_SECONDS,
        max_retries: int = 5,
        min_interval: float = 6.5,
    ) -> None:
        super().__init__(timeout=timeout, max_retries=max_retries, min_interval=min_interval)
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_GEMINI_MODEL
        self.temperature = temperature
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMError(
                "GOOGLE_API_KEY is not set. Copy .env.example to .env and fill it in, or use "
                "LLM_PROVIDER=local. Never pass the key on the command line."
            )
        self._key = key

    @staticmethod
    def _tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Gemini wants OpenAPI-style upper-case type names in its function declarations."""
        if not tools:
            return None

        def upper(node: Any) -> Any:
            if isinstance(node, dict):
                out = {k: upper(v) for k, v in node.items()}
                if isinstance(out.get("type"), str):
                    out["type"] = out["type"].upper()
                return out
            if isinstance(node, list):
                return [upper(v) for v in node]
            return node

        return [upper(t) for t in tools]

    @staticmethod
    def _contents(history: list[Turn]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for turn in history:
            if turn.role == "model":
                parts: list[dict[str, Any]] = []
                if turn.text:
                    parts.append({"text": turn.text})
                parts.extend({"functionCall": {"name": c.name, "args": c.args}} for c in turn.calls)
                contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            elif turn.results:
                # Gemini returns tool output in the `user` role as functionResponse parts.
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {"functionResponse": {"name": r.call.name, "response": r.payload}}
                            for r in turn.results
                        ],
                    }
                )
            else:
                contents.append({"role": "user", "parts": [{"text": turn.text}]})
        return contents

    def generate(
        self, *, system: str, history: list[Turn], tools: list[dict[str, Any]] | None = None
    ) -> Reply:
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": self._contents(history),
            "generationConfig": {"temperature": self.temperature},
        }
        converted = self._tools(tools)
        if converted:
            body["tools"] = [{"function_declarations": converted}]

        started = time.monotonic()
        data = self.post(
            f"{GEMINI_API_ROOT}/models/{self.model}:generateContent",
            body,
            {"x-goog-api-key": self._key, "Content-Type": "application/json"},
        )
        elapsed = time.monotonic() - started

        meta = data.get("usageMetadata") or {}
        usage = Usage(
            prompt_tokens=int(meta.get("promptTokenCount", 0)),
            output_tokens=int(meta.get("candidatesTokenCount", 0)),
            total_tokens=int(meta.get("totalTokenCount", 0)),
            calls=1,
            seconds=elapsed,
        )
        self.usage.add(usage)

        candidates = data.get("candidates") or []
        if not candidates:
            # A blocked prompt returns no candidates at all, with the reason alongside.
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"model returned nothing: {reason}")

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_chunks: list[str] = []
        calls: list[ToolCall] = []
        for part in parts:
            if "text" in part:
                text_chunks.append(part["text"])
            fn = part.get("functionCall")
            if fn:
                calls.append(ToolCall(name=fn.get("name", ""), args=dict(fn.get("args") or {})))

        return Reply(text="".join(text_chunks).strip(), calls=calls, usage=usage)


# --- Selection ----------------------------------------------------------------------------------


def build_llm(provider: str | None = None, model: str | None = None) -> LLM:
    """Construct the client named by `LLM_PROVIDER`.

    One factory, shared by both modes, so they cannot end up on different models or providers —
    which would make the headline comparison meaningless.
    """
    name = (provider or DEFAULT_PROVIDER or "local").strip().lower()
    if name in {"openai", "responses"}:
        # Hosted OpenAI goes through the Responses API: the reasoning models this key serves
        # will not use function tools on /chat/completions unless reasoning is turned off.
        return ResponsesClient(model)
    if name in {"local", "lmstudio", "openai-chat", "openai-compatible", "openai_compatible"}:
        # A local server (LM Studio, llama.cpp, vLLM, Ollama) speaking /chat/completions.
        return OpenAIClient(model)
    if name in {"google", "gemini"}:
        return GeminiClient(model)
    raise LLMError(
        f"unknown LLM_PROVIDER {name!r}; expected 'local', 'openai', or 'google'"
    )


def user_turn(text: str) -> Turn:
    return Turn(role="user", text=text)
