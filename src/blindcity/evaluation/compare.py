"""Compare modes across runs, in a form that survives being read a week later.

The headline number is a difference between modes, so the comparison — not the individual run —
is the artifact worth keeping. It records what each mode was given, what it scored, and what it
cost, plus enough provenance (model, seed, catalog contents, git commit) that a number can be
traced back to the code that produced it.

Deliberately reports the spread across repeats rather than a single figure. Measured run-to-run
variation on one seed is about 0.02 of final index, which is the same size as the difference
between two of the three modes; a comparison that printed one number per mode would invite a
conclusion the data does not support.
"""

from __future__ import annotations

import itertools
import json
import statistics
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModeSummary:
    """Every run of one mode, reduced to what a reader needs."""

    mode: str
    runs: int
    final_index: list[float] = field(default_factory=list)
    green_turn: list[int | None] = field(default_factory=list)
    total_tokens: list[int] = field(default_factory=list)
    llm_calls: list[int] = field(default_factory=list)
    llm_seconds: list[float] = field(default_factory=list)
    sql_queries: list[int] = field(default_factory=list)
    timeouts: int = 0
    infrastructure_failures: int = 0
    # Turns that produced no decision at all -- an LLM failure, or an advisor that never answered.
    # Tracked apart from `infrastructure_failures`, which counts lost *queries*: the model adapts
    # to a lost query and plays on, where a lost turn is a hole in the run the score cannot show.
    # A twelve-turn run that played ten is not a worse strategy, it is a different experiment.
    lost_turns: int = 0
    # Every model id seen across this mode's runs. A list rather than one value because the whole
    # comparison rests on the modes sharing a model, and the report has to be able to say so from
    # the recorded runs rather than from what the operator meant to do.
    models: list[str] = field(default_factory=list)

    @property
    def mean_index(self) -> float:
        return statistics.fmean(self.final_index) if self.final_index else 0.0

    @property
    def index_spread(self) -> float:
        return (max(self.final_index) - min(self.final_index)) if len(self.final_index) > 1 else 0.0

    @property
    def recovered(self) -> int:
        return sum(1 for g in self.green_turn if g is not None)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mean_index"] = round(self.mean_index, 4)
        d["index_spread"] = round(self.index_spread, 4)
        d["recovered_runs"] = self.recovered
        return d


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def collect(paths: list[Path]) -> dict[str, ModeSummary]:
    """Fold a set of run-result JSON files into one summary per mode."""
    summaries: dict[str, ModeSummary] = {}
    for path in sorted(paths):
        # Every run writes a `.agent.json` sidecar beside its result, so any glob that catches
        # one catches the other. Skipping here rather than at each call site: a caller that
        # forgets gets a KeyError on a file that was never a run result.
        if path.name.endswith(".agent.json") or path.name.endswith(".transcript.jsonl"):
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        if "mode" not in result or "final_index" not in result:
            continue
        mode = result["mode"]
        side = path.with_suffix(".agent.json")
        report = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}

        s = summaries.setdefault(mode, ModeSummary(mode=mode, runs=0))
        s.runs += 1
        s.final_index.append(round(result["final_index"], 4))
        s.green_turn.append(result["green_turn"])
        usage = report.get("usage", {})
        s.total_tokens.append(usage.get("total_tokens", 0))
        s.llm_calls.append(usage.get("calls", 0))
        s.llm_seconds.append(round(usage.get("seconds", 0.0), 1))
        s.sql_queries.append(sum(t.get("sql_calls", 0) for t in report.get("turns", [])))
        model = report.get("model")
        if isinstance(model, str) and model and model not in s.models:
            s.models.append(model)
        s.lost_turns += sum(1 for turn in report.get("turns", []) if turn.get("error"))
        s.lost_turns += len(report.get("advisor_errors") or [])
        s.timeouts += report.get("timeouts", 0)
        s.infrastructure_failures += report.get("infrastructure_failures", 0)
    return summaries


# The order modes are expected to improve in. Reported as an observation, never enforced: if the
# ordering does not hold, that is the finding, and a comparison that quietly sorted by score
# would hide exactly the result worth knowing.
EXPECTED_ORDER = ("agent_raw", "agent_datahub", "agent_datahub_live")


def _model_line(summaries: dict[str, ModeSummary], fallback: str) -> tuple[str, str | None]:
    """What model the runs actually used, and a warning if they disagree.

    The A/B is only worth anything if every mode ran the same model, and that is a fact about the
    recorded runs, not about the command line -- so it is read back out of them. `agent_analytics`
    is excluded from the comparison: it reports its advisor's endpoint rather than a model id,
    because the model is configured inside a service we do not own. Its parity is enforced at
    runtime instead, by `AnalyticsAgentAdvisor.preflight`.

    `good_policy` and `bad_policy` are excluded for the opposite reason: they are fixed lever sets
    that call no model at all, so "scripted" is the honest thing for them to report and is not a
    disagreement with anything. Flagging it would fire the mismatch warning on every complete run
    -- and a warning that is always wrong is a warning nobody reads when it is right.
    """
    exempt = {"agent_analytics", "good_policy", "bad_policy"}
    seen: dict[str, list[str]] = {}
    for name, s in summaries.items():
        if name in exempt:
            continue
        for m in s.models:
            seen.setdefault(m, []).append(name)
    if not seen:
        return fallback, None
    if len(seen) == 1:
        return next(iter(seen)), None
    detail = "; ".join(f"`{m}`: {', '.join(sorted(modes))}" for m, modes in sorted(seen.items()))
    return (
        "MIXED",
        "**These modes did not run the same model, so their scores are not comparable.** "
        + detail,
    )


def markdown(summaries: dict[str, ModeSummary], *, threshold: float, seed: int, model: str) -> str:
    ordered = [m for m in EXPECTED_ORDER if m in summaries]
    ordered += [m for m in sorted(summaries) if m not in EXPECTED_ORDER]

    rows = [
        "| Mode | Runs | Mean index | Spread | Recovered | Green turn | Tokens | LLM calls | SQL |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ordered:
        s = summaries[name]
        greens = ", ".join("-" if g is None else str(g) for g in s.green_turn)
        rows.append(
            f"| `{name}` | {s.runs} | **{s.mean_index:.4f}** | {s.index_spread:.4f} | "
            f"{s.recovered}/{s.runs} | {greens} | "
            f"{statistics.fmean(s.total_tokens):,.0f} | {statistics.fmean(s.llm_calls):.0f} | "
            f"{statistics.fmean(s.sql_queries):.0f} |"
        )

    resolved, mismatch = _model_line(summaries, model)
    lines = [
        "# Blind City — mode comparison",
        "",
        (
            f"Seed {seed} · model `{resolved}` · green threshold {threshold} · "
            f"commit `{git_commit()}`"
        ),
        "",
        *rows,
        "",
    ]
    if mismatch:
        lines += [mismatch, ""]

    # Only meaningful when at least two of the benchmark modes are present. A dry run plays the
    # scripted policies, which have no expected ordering to check against.
    benchmark_modes = [m for m in EXPECTED_ORDER if m in summaries]
    if len(benchmark_modes) > 1:
        scored = [(summaries[m].mean_index, m) for m in benchmark_modes]
        actual = [m for _, m in sorted(scored, reverse=True)]
        expected = benchmark_modes[::-1]
        if actual == expected:
            lines.append(f"Ordering as expected: {' > '.join(actual)}.")
        else:
            lines.append(
                f"**Ordering not as expected.** Observed {' > '.join(actual)}; "
                f"expected {' > '.join(expected)}."
            )

    spreads = [s.index_spread for s in summaries.values() if s.runs > 1]
    if spreads:
        worst = max(spreads)
        gaps = [
            abs(summaries[a].mean_index - summaries[b].mean_index)
            for a, b in itertools.pairwise(ordered)
        ]
        if gaps and worst >= min(gaps):
            lines += [
                "",
                (
                    f"Run-to-run spread reaches {worst:.4f}, which is at least as large as the "
                    f"smallest gap between modes ({min(gaps):.4f}). Differences that size are "
                    "not distinguishable from noise at this number of repeats."
                ),
            ]
    else:
        lines += [
            "",
            (
                "Single run per mode: no variance estimate. Measured spread on repeated "
                "identical runs has reached 0.02 of final index, so treat gaps below that as "
                "unresolved."
            ),
        ]

    incomplete = {m: s.lost_turns for m, s in summaries.items() if s.lost_turns}
    if incomplete:
        lines += [
            "",
            (
                "**Incomplete runs.** "
                + "; ".join(f"`{m}` lost {n} turn(s) to an error" for m, n in sorted(incomplete.items()))
                + ". A lost turn is a decision never made, not a decision made badly -- these "
                "scores are lower bounds and are not comparable with the rest of the table."
            ),
        ]

    degraded = [m for m, s in summaries.items() if s.infrastructure_failures]
    if degraded:
        lines += [
            "",
            f"**Degraded runs** (queries lost to timeouts or a dead warehouse): {degraded}.",
        ]
    return "\n".join(lines) + "\n"
