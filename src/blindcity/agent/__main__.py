"""Entry point for `uv run agent`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from blindcity.console import configure_console


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Play a Blind City scenario as one benchmark mode.",
    )
    parser.add_argument(
        "--mode",
        choices=("agent_datahub", "agent_raw"),
        default="agent_datahub",
        help="'agent_raw' is the A/B control: same model, prompt, seed, tool budget and SQL "
        "access, with only the DataHub catalog context removed. Keep it honest (AGENTS.md).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id. Defaults to $LLM_MODEL. Both modes must use the same one -- that is a "
        "fairness requirement, not a preference.",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Truncate the scenario to this many turns, for smoke tests. The scored run uses "
        "the scenario's full turn budget.",
    )
    parser.add_argument(
        "--tool-budget",
        type=int,
        default=None,
        help="Tool calls the model may make per turn before it must commit.",
    )
    parser.add_argument(
        "--provider",
        choices=("local", "openai", "google"),
        default=None,
        help="Where inference runs. Defaults to $LLM_PROVIDER. 'local' and 'openai' use the same "
        "OpenAI-compatible client and differ only in $LLM_BASE_URL and the key.",
    )
    parser.add_argument("--out", default=None, help="Write the run result JSON here.")
    parser.add_argument(
        "--keep-views",
        action="store_true",
        help="Leave the per-run SQL views in place so you can inspect what the agent could see.",
    )
    parser.add_argument(
        "--keep-warehouse",
        action="store_true",
        help="Append to the existing warehouse instead of clearing it first. The default is a "
        "clean slate every run, so no run inherits another's rows, planner statistics, or "
        "leftover views. Use this to compare a new run against data already loaded.",
    )
    parser.add_argument(
        "--force-clean",
        action="store_true",
        help="Clear the warehouse even when another run looks like it is still playing. This "
        "deletes that run's data; only use it when you know the process is dead.",
    )
    return parser


def main() -> int:
    configure_console()
    args = build_parser().parse_args()

    # Imported here so `--help` works without a database, a key, or a running stack.
    from blindcity.agent.controller import DEFAULT_TOOL_BUDGET
    from blindcity.agent.llm import LLMError, build_llm
    from blindcity.agent.run import estimate_full_run, run_mode
    from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS

    try:
        run = run_mode(
            args.mode,
            llm=build_llm(args.provider, args.model),
            turns=args.turns,
            tool_budget=args.tool_budget or DEFAULT_TOOL_BUDGET,
            keep_views=args.keep_views,
            clean_warehouse=not args.keep_warehouse,
            force_clean=args.force_clean,
        )
    except LLMError as exc:
        print(f"agent: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"agent: run failed: {exc}", file=sys.stderr)
        return 1

    result, report = run.result, run.report
    played = len(result.turns)
    print(
        f"agent: mode={result.mode} model={report['model']} catalog={report['catalog']} "
        f"turns={played} recovered={result.recovered} green_turn={result.green_turn} "
        f"final_index={result.final_index:.4f}"
    )
    usage = report["usage"]
    print(
        f"agent: tokens prompt={usage['prompt_tokens']:,} output={usage['output_tokens']:,} "
        f"total={usage['total_tokens']:,} llm_calls={usage['calls']} "
        f"llm_seconds={usage['seconds']} wall_seconds={run.wall_seconds:.1f}"
    )

    if played and played < INFRASTRUCTURE_CRISIS.turn_budget:
        est = estimate_full_run(report, played, INFRASTRUCTURE_CRISIS.turn_budget)
        print(
            f"agent: extrapolated full run ({est['turn_budget']} turns) "
            f"total_tokens={est['total_tokens']:,} llm_calls={est['llm_calls']} "
            f"llm_seconds={est['llm_seconds']}"
        )

    failed = [t for t in report["turns"] if t.get("error")]
    if failed:
        print(f"agent: {len(failed)} turn(s) hit an LLM error; first: {failed[0]['error'][:200]}")

    # A model asking for a table that does not exist is exploration, not damage -- report it flatly.
    query_errors = report.get("tool_failures", 0) - report.get("infrastructure_failures", 0)
    if query_errors:
        print(f"agent: {query_errors} query error(s) the model recovered from (bad table or column)")

    # Degradation is different and must never read as a clean run: these do not fail the turn, the
    # model adapts and carries on, so this line is the only trace that a diagnosis it asked for
    # never came back. One live run lost four queries and three minutes and printed "0 errors".
    infra = report.get("infrastructure_failures", 0)
    if infra:
        turns_hit = [t["turn"] for t in report["turns"] if t.get("infrastructure_errors")]
        print(
            f"agent: DEGRADED -- {infra} query/queries lost to timeouts or a dead warehouse "
            f"on turn(s) {turns_hit}"
        )
        print("agent: the score stands, but the model was denied data it asked for.")

    if args.out:
        result.write_json(args.out)
        side = Path(args.out).with_suffix(".agent.json")
        side.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"agent: wrote {args.out} and {side}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
