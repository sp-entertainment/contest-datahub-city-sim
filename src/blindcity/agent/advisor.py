"""Ask DataHub's own Analytics Agent what to do, and act on the answer.

The other two modes reason over the warehouse themselves: our controller writes the SQL, reads the
rows, and decides. This one does not. It behaves like a manager with an analyst on staff — it
describes the situation in plain English, asks which levers to move, and acts on what comes back.

That makes it a different question from the other modes. `agent_raw` and `agent_datahub_live` ask
"is a catalogued warehouse worth more to an agent than an uncatalogued one". This asks "is
DataHub's own analytics agent, pointed at the same warehouse, better at governing the city than an
agent we wrote". Ours writes SQL and holds a plan across turns; theirs is a text-to-SQL analyst
grounded in the catalog, with no memory of the city between questions except what we tell it.

The advisor never actuates anything. It returns prose; the controller parses lever values out of
it and applies them, exactly as a person would read an analyst's answer and then pull the levers
themselves. Nothing the advisor says can move a lever the controller did not choose to move.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from blindcity.levers import LEVERS

# The Analytics Agent answers over SSE and a real analysis runs to tens of seconds. This bounds one
# question, not the run: a question that times out costs that turn's advice, not the mode.
ADVISOR_TIMEOUT_SECONDS = float(240)

DEFAULT_BASE_URL = "http://localhost:8100"


class LLMMismatch(RuntimeError):
    """The advisor is not configured like the modes it is being compared against."""


@dataclass
class Advice:
    """One answer from the advisor, and what it cost."""

    question: str
    answer: str
    levers: dict[str, float] = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None
    queries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer[:4000],
            "levers": self.levers,
            "seconds": round(self.seconds, 2),
            "error": self.error,
            "queries": self.queries,
        }


def parse_levers(text: str) -> dict[str, float]:
    """Pull lever settings out of an analyst's prose.

    Deliberately forgiving about formatting and strict about names and ranges: the advisor is a
    third-party component answering in free text, and a brittle parser would silently score the
    mode on the parser rather than on the advice. Anything not named as a real lever is ignored,
    and every value goes through the same clamp the other modes' `set_levers` uses.

    Accepts `income_tax_rate = 0.11`, `income_tax_rate: 0.11`, `**income_tax_rate**: 0.11`,
    `- income_tax_rate → 0.11`, and the same with thousands separators or a currency prefix.
    """
    found: dict[str, float] = {}
    for name in LEVERS:
        # Last occurrence wins: analysts frequently restate the recommendation in a summary at the
        # end, and the summary is the considered answer.
        pattern = re.compile(
            rf"{re.escape(name)}\**\s*(?:=|:|->|→|to|at)\s*\**\s*\$?([0-9][0-9,_]*(?:\.[0-9]+)?)",
            re.IGNORECASE,
        )
        matches = pattern.findall(text)
        if not matches:
            continue
        raw = matches[-1].replace(",", "").replace("_", "")
        try:
            found[name] = LEVERS[name].clamp(float(raw))
        except ValueError:
            continue
    return found


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
            json={"title": "Blind City", "engine_name": self.engine},
        )
        r.raise_for_status()
        self.conversation_id = r.json()["id"]
        return self.conversation_id

    def ask(self, question: str) -> Advice:
        started = time.monotonic()
        try:
            with self._client() as client:
                conv = self.start(client)
                answer, statements = self._send(client, conv, question)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return Advice(
                question=question,
                answer="",
                seconds=time.monotonic() - started,
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
            )
        return Advice(
            question=question,
            answer=answer,
            levers=parse_levers(answer),
            seconds=time.monotonic() - started,
            queries=statements,
        )

    def _send(self, client: httpx.Client, conv: str, question: str) -> tuple[str, list[str]]:
        """Post the question and read the streamed reply to completion.

        Events arrive as `{"event": KIND, "payload": {...}}`. `TEXT` carries the answer a token at
        a time, `SQL` the statements it ran, and `USAGE` its token counts -- which are recorded so
        this mode's cost sits beside the others' rather than reading as free.
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
                elif kind == "USAGE":
                    for key in self.tokens:
                        self.tokens[key] += int(payload.get(key, 0) or 0)
                elif kind == "ERROR":
                    message = payload.get("error") or payload.get("message")
                    if isinstance(message, str) and message:
                        raise ValueError(message[:300])
        return "".join(text_parts).strip(), statements
