"""Record exactly what each mode was sent and what came back.

Every context bug this project has hit was invisible in the results and obvious in the transcript.
The catalog promised a glossary and delivered none for the whole of Slice 6, because twenty terms
were emitted to DataHub and never linked to a dataset -- the run reports looked perfect. Before
that, query results came back as a list of column names, and the only symptom was a model that
asked the same question six ways. A score tells you a mode did badly. It never tells you what the
mode could see.

So this wraps the LLM at the provider-neutral boundary and writes one JSON line per call: the
system prompt, the full conversation as the model received it, and the reply. It is the ground
truth for "what did this agent actually get", and it is the only artifact that can settle a
question about parity between two modes after the fact.

Deliberately a wrapper rather than hooks inside the controller: the controller must stay the one
place the loop lives, and a recorder that cannot alter the conversation cannot bias a run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from blindcity.agent.llm import LLM, Reply, Turn


def _turn_to_dict(turn: Turn) -> dict[str, Any]:
    return {
        "role": turn.role,
        "text": turn.text,
        "calls": [{"id": c.id, "name": c.name, "args": c.args} for c in turn.calls],
        "results": [
            {"call_id": r.call.id, "name": r.call.name, "payload": r.payload} for r in turn.results
        ],
    }


class RecordingLLM:
    """Wraps an LLM and appends every exchange to a JSONL file. Passes replies through untouched."""

    def __init__(self, inner: LLM, path: str | Path, *, mode: str) -> None:
        self.inner = inner
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate any earlier transcript at this path so a rerun cannot be read as one long run.
        self.path.write_text("", encoding="utf-8")
        self.mode = mode
        self.calls = 0

    @property
    def model(self) -> str:
        return self.inner.model

    def __getattr__(self, name: str) -> Any:
        """Anything this wrapper does not define, read from the client underneath.

        `model` was proxied explicitly and nothing else was, which meant the report's
        `reasoning_effort` and `reasoning_sent` both read `None` on every run that recorded a
        transcript -- which, since transcripts became the default, is every run. The reasoning
        budget was being applied correctly and the record of it said "unknown".

        That is this module's own failure mode turned on itself: the layer that exists to make a
        run auditable was quietly deleting a field from the audit. Delegating by name rather than
        listing the attributes is the point -- a future field on the client shows up without
        anyone remembering to add it here.
        """
        return getattr(self.inner, name)

    def _write(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def generate(
        self, *, system: str, history: list[Turn], tools: list[dict[str, Any]] | None = None
    ) -> Reply:
        self.calls += 1
        index = self.calls
        # Written before the call, so a crash or a hang still leaves evidence of what was sent.
        self._write(
            {
                "mode": self.mode,
                "call": index,
                "phase": "request",
                "system": system,
                "tools": [t.get("name") for t in (tools or [])],
                "history": [_turn_to_dict(t) for t in history],
            }
        )
        try:
            reply = self.inner.generate(system=system, history=history, tools=tools)
        except Exception as exc:
            self._write(
                {
                    "mode": self.mode,
                    "call": index,
                    "phase": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise
        self._write(
            {
                "mode": self.mode,
                "call": index,
                "phase": "reply",
                "text": reply.text,
                "calls": [{"id": c.id, "name": c.name, "args": c.args} for c in reply.calls],
                "usage": reply.usage.to_dict(),
            }
        )
        return reply
