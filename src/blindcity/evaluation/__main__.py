"""Entry point for `uv run eval` — drive every mode through one scenario and compare them.

Two ways to run it, and the default is the free one:

  * `--dry-run` plays scripted controllers instead of the model. It exercises the whole harness,
    scoring and comparison path at zero cost, which is how the plumbing gets verified without
    spending an evaluation. The scripted policies bracket the agents, so a dry run also shows
    whether the scenario itself is still calibrated.
  * `--live` spends real tokens. Running the scored evaluation is a human decision (H3): it costs
    money and produces the number the submission is built on, so this never happens by accident.

`--repeat` exists because one run per mode is not a measurement. Repeated identical runs on this
scenario have varied by about 0.02 of final index, which is the same size as the gap between two
of the three modes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from blindcity.console import configure_console

# The three benchmark modes, in the order the comparison expects them to score. `agent_analytics`
# is runnable but not in this default: it answers a different question -- "is DataHub's own agent
# better at this than one we wrote" -- and folding it into the A/B would invite reading its score
# as another point on the same curve. `--modes` takes it explicitly.
MODES = ("agent_raw", "agent_datahub", "agent_datahub_live")
RUNNABLE_MODES = (*MODES, "agent_analytics")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval",
        description="Run the catalog A/B evaluation across every mode and compare them.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=list(MODES),
        choices=list(RUNNABLE_MODES),
        help="Modes to run, in any order. Defaults to the three benchmark modes; "
        "'agent_analytics' needs a running Analytics Agent (infra/analytics-agent/README.md).",
    )
    parser.add_argument(
        "--repeat", type=int, default=1,
        help="Runs per mode. More than one gives a variance estimate; one does not.",
    )
    parser.add_argument("--out-dir", default="results/eval", help="Where run JSON is written.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Play scripted policies instead of the model. Free, and verifies the whole path.",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Spend real tokens. This is H3 and is a human decision; nothing else sets it.",
    )
    parser.add_argument(
        "--collect-only", nargs="*", default=None, metavar="GLOB",
        help="Skip running and just summarise existing result files, e.g. 'results/*.json'.",
    )
    parser.add_argument("--model", default=None, help="Model id. Defaults to $LLM_MODEL.")
    return parser


def _dry_run(out_dir: Path, repeat: int) -> list[Path]:
    """Play the calibrated scripted policies so the harness can be proven without spending."""
    from blindcity.benchmark.controller import bad_controller, good_controller
    from blindcity.benchmark.harness import RunHarness
    from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS

    written: list[Path] = []
    for label, controller in (("good_recovery", good_controller), ("bad_neglect", bad_controller)):
        for i in range(repeat):
            result = RunHarness(INFRASTRUCTURE_CRISIS).run(controller(), mode=label)
            path = out_dir / f"dry-{label}-{i}.json"
            result.write_json(path)
            written.append(path)
            print(
                f"eval: {label} run {i + 1}/{repeat} recovered={result.recovered} "
                f"green_turn={result.green_turn} final_index={result.final_index:.4f}"
            )
    return written


def _live_run(out_dir: Path, modes: list[str], repeat: int, model: str | None) -> list[Path]:
    from blindcity.agent.run import run_mode

    written: list[Path] = []
    for mode in modes:
        for i in range(repeat):
            run = run_mode(mode, model=model)
            path = out_dir / f"{mode}-{i}.json"
            run.result.write_json(path)
            path.with_suffix(".agent.json").write_text(
                json.dumps(run.report, indent=2), encoding="utf-8"
            )
            written.append(path)
            print(
                f"eval: {mode} run {i + 1}/{repeat} recovered={run.result.recovered} "
                f"green_turn={run.result.green_turn} "
                f"final_index={run.result.final_index:.4f} "
                f"tokens={run.report['usage']['total_tokens']:,}"
            )
    return written


def main() -> int:
    configure_console()
    args = build_parser().parse_args()

    from blindcity.benchmark.health import GREEN_THRESHOLD
    from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS
    from blindcity.evaluation.compare import collect, markdown

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.collect_only is not None:
        paths = [p for pattern in args.collect_only for p in Path().glob(pattern)]
        paths = [p for p in paths if not p.name.endswith(".agent.json")]
        if not paths:
            print("eval: no result files matched", file=sys.stderr)
            return 1
    elif args.dry_run:
        paths = _dry_run(out_dir, args.repeat)
    elif args.live:
        paths = _live_run(out_dir, args.modes, args.repeat, args.model)
    else:
        # Refusing rather than defaulting either way. Defaulting to --live would spend money on a
        # bare `uv run eval`; defaulting to --dry-run would let someone believe they had run the
        # real evaluation when they had not.
        print(
            "eval: choose one of --dry-run (free, verifies the harness) or --live (spends real "
            "tokens; this is human task H3).",
            file=sys.stderr,
        )
        return 2

    summaries = collect(paths)
    report = markdown(
        summaries,
        threshold=GREEN_THRESHOLD,
        seed=INFRASTRUCTURE_CRISIS.seed,
        model=args.model or "scripted" if args.dry_run else (args.model or "$LLM_MODEL"),
    )
    print()
    print(report)

    (out_dir / "comparison.md").write_text(report, encoding="utf-8")
    (out_dir / "comparison.json").write_text(
        json.dumps({m: s.to_dict() for m, s in summaries.items()}, indent=2), encoding="utf-8"
    )
    print(f"eval: wrote {out_dir / 'comparison.md'} and {out_dir / 'comparison.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
