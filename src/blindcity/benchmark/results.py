"""Durable results format for comparing runs across days and modes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TurnRecord:
    turn: int
    tick: int
    levers: dict[str, float]
    components: dict[str, float]
    index: float
    green: bool


@dataclass
class RunResult:
    """One complete scenario run under one controller."""

    scenario_name: str
    seed: int
    controller_name: str
    mode: str  # human | agent_datahub | agent_raw | scripted
    run_id: str  # durable id (uuid or warehouse run_id as string)
    turn_budget: int
    green_threshold: float
    baseline_population: int
    recovered: bool
    green_turn: int | None  # first turn index where index >= green, else None
    final_index: float
    turns: list[TurnRecord] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def write_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @staticmethod
    def read_json(path: str | Path) -> RunResult:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        turns = [TurnRecord(**t) for t in raw.pop("turns")]
        return RunResult(turns=turns, **raw)
