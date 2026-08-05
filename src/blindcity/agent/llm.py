"""Minimal Gemini client with function calling.

Deliberately hand-rolled over `httpx` rather than pulling in an SDK. The agent needs three
things — send a conversation, receive either text or a function call, report token usage — and
an SDK would add a dependency, a version to manage, and a layer between us and the exact
request both arms send. Since the benchmark's validity rests on the two arms being byte-identical
apart from one block of context, that transparency is worth more than the convenience.

The key is read from the environment and never logged, never echoed into a prompt, and never
written into a result file. It travels in the `x-goog-api-key` header, never a query string,
where it would land in logs and proxy history.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from blindcity import config  # noqa: F401  -- imported for its .env loading side effect

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

# Both arms must use the same model. That is a fairness requirement, not a preference.
#
# Verified against the live key on 2026-08-03: `gemini-2.5-flash` now 404s with "no longer
# available to new users" even though it still appears in the models listing, and every `pro`
# model 429s with a quota error because the key has no paid tier. Working models are
# `gemini-3.6-flash`, `gemini-3.5-flash`, and `gemini-flash-latest`. Re-check before H3 rather
# than trusting this comment — availability moved under us once already.
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gemini-3.6-flash")


class LLMError(RuntimeError):
    """The provider refused, failed, or returned something unusable."""


@dataclass
class Usage:
    """Token accounting, so H3 can be budgeted before it is paid for."""

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
class FunctionCall:
    name: str
    args: dict[str, Any]


@dataclass
class Reply:
    """One model turn: free text, function calls, or both."""

    text: str = ""
    calls: list[FunctionCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    raw_parts: list[dict[str, Any]] = field(default_factory=list)


class LLMClient:
    """Blocking Gemini client. One instance is shared by both arms so they cannot drift."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        temperature: float = 0.0,
        timeout: float = 90.0,
        max_retries: int = 5,
        min_interval: float = 6.5,
        backoff_base: float = 8.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        # ~9 requests/minute, under the free tier's limit. Override with LLM_MIN_INTERVAL if the
        # key gets a paid tier, where this is pure waiting.
        self.min_interval = float(os.environ.get("LLM_MIN_INTERVAL", min_interval))
        self.backoff_base = backoff_base
        self._last_request = 0.0
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMError(
                "GOOGLE_API_KEY is not set. Copy .env.example to .env and fill it in; see "
                "docs/ENVIRONMENT.md. Never pass the key on the command line."
            )
        self._key = key
        self.usage = Usage()

    def generate(
        self,
        *,
        system: str,
        contents: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Reply:
        """One request/response round trip.

        `contents` is the running conversation in Gemini's wire format; the caller owns it so the
        agent loop can append tool results and call again.
        """
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": self.temperature},
        }
        if tools:
            body["tools"] = [{"function_declarations": tools}]

        url = f"{API_ROOT}/models/{self.model}:generateContent"
        started = time.monotonic()
        data = self._post_with_retries(url, body)
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
        calls: list[FunctionCall] = []
        for part in parts:
            if "text" in part:
                text_chunks.append(part["text"])
            fn = part.get("functionCall")
            if fn:
                calls.append(FunctionCall(name=fn.get("name", ""), args=dict(fn.get("args") or {})))

        return Reply(
            text="".join(text_chunks).strip(),
            calls=calls,
            usage=usage,
            raw_parts=parts,
        )

    def _pace(self) -> None:
        """Hold a minimum gap between requests.

        The key is on the free tier, which limits requests per minute. Firing a turn's tool calls
        back to back trips that limit within seconds, and no amount of retrying inside the same
        minute clears it — the first live runs failed every turn this way while a single call
        made by hand succeeded instantly. A full 36-turn run is roughly 216 calls per arm, so
        pacing is the difference between an evaluation and a pile of failed turns.
        """
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _retry_after(payload: dict[str, Any]) -> float | None:
        """Google returns its own backoff in the error details. Prefer it to a guess."""
        for detail in (payload.get("error") or {}).get("details") or []:
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                try:
                    return float(delay[:-1])
                except ValueError:
                    continue
        return None

    def _post_with_retries(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._pace()
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(url, json=body, headers=headers)
                self._last_request = time.monotonic()
                if r.status_code == 200:
                    return r.json()
                # 429 and 5xx are worth another go; any other 4xx is our bug, and retrying
                # just burns quota against the same broken request.
                if r.status_code != 429 and r.status_code < 500:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                last = LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                sleep_for = None
                if r.status_code == 429:
                    try:
                        sleep_for = self._retry_after(r.json())
                    except ValueError:
                        sleep_for = None
            except httpx.HTTPError as exc:
                last = exc
                sleep_for = None
                self._last_request = time.monotonic()
            if attempt < self.max_retries - 1:
                time.sleep(sleep_for if sleep_for else self.backoff_base * (2**attempt))
        raise LLMError(f"request failed after {self.max_retries} attempts: {last}")


def user_turn(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_turn(parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"role": "model", "parts": parts}


def tool_results_turn(results: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Gemini expects tool output back in the `user` role as functionResponse parts."""
    return {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": name, "response": payload}} for name, payload in results
        ],
    }
