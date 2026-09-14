"""The City Sim Agent Benchmark command line. One entry point, four subcommands.

    blindcity sim      generate a city's history, or serve the interactive viewer
    blindcity emit     publish the catalog snapshot to DataHub
    blindcity run      play one benchmark mode
    blindcity compare  summarise result files into one table

There were four separate console scripts until 2026-08-10, two of which -- `agent` and `eval` --
were independent wrappers around the same engine. They drifted three times, each divergence
invisible until something was already wrong: the eval path wrote no transcripts, could not clear a
stale warehouse, and never printed the DEGRADED block, so a twelve-run batch could show a clean
table while runs were losing queries to timeouts. One parser and one set of handlers means a flag
is added once and every run gets it.

This module owns argument parsing and nothing else. Each subcommand's work lives in
`blindcity/commands/`, imported only when that subcommand actually runs, so `--help` works on a
clean checkout with no database, no key and no Docker.
"""

from __future__ import annotations

import argparse
import sys

from blindcity.console import configure_console

# Repeats are a shell loop, not a flag. Every parameter stays reachable inside the loop and there
# is no batch runner to drift away from the single-run path.
EPILOG = """\
examples:
  blindcity sim --seed 42 --years 20
  blindcity emit
  blindcity run --mode agent_datahub_live --out results/live.json
  blindcity compare "results/*.json"

  # three runs of every mode -- bash, not a --repeat flag
  for i in 1 2 3; do
    for m in agent_raw agent_datahub agent_datahub_live; do
      blindcity run --mode $m --out results/$m-$i.json --overwrite-datahub true
    done
  done
"""


def _tristate(value: str) -> bool:
    """Parse --overwrite-datahub. Absent is not this function's business; argparse handles it."""
    lowered = value.strip().lower()
    if lowered in {"true", "t", "yes", "y", "1"}:
        return True
    if lowered in {"false", "f", "no", "n", "0"}:
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def _add_overwrite(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--overwrite-datahub",
        type=_tristate,
        default=None,
        metavar="true|false",
        help="What to do when DataHub differs from this commit's catalog snapshot. "
        "'true' replaces it, 'false' keeps DataHub's values and runs against them. Omit it and "
        "you are asked, showing the difference first. When DataHub is empty or already matches, "
        "the snapshot is published either way -- there is nothing to lose.",
    )


def build_parser() -> argparse.ArgumentParser:
    from blindcity import config

    parser = argparse.ArgumentParser(
        prog="blindcity",
        description="City Sim Agent Benchmark: a benchmark for whether a data catalog makes an agent better.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # --- sim --------------------------------------------------------------------------------
    p_sim = sub.add_parser(
        "sim",
        help="Generate a city's history into the warehouse, or serve the viewer.",
        description="Run the city simulation. Appends a new run to the warehouse by default.",
    )
    p_sim.add_argument("--seed", type=int, default=42, help="Same seed, same city.")
    p_sim.add_argument("--years", type=int, default=20, help="Simulated years to generate.")
    p_sim.add_argument("--serve", action="store_true", help="Serve the control surface instead.")
    p_sim.add_argument("--host", default="127.0.0.1", help="Bind host for --serve.")
    p_sim.add_argument("--port", type=int, default=8000, help="Bind port for --serve.")
    p_sim.add_argument(
        "--no-warehouse", action="store_true", help="In memory only; write no rows."
    )
    p_sim.add_argument(
        "--reset-warehouse",
        action="store_true",
        help="Drop and recreate the tables first. The default appends, so several cities can "
        "coexist; `blindcity run` is the opposite and clears by default.",
    )

    # --- emit -------------------------------------------------------------------------------
    p_emit = sub.add_parser(
        "emit",
        help="Publish the catalog snapshot to DataHub.",
        description="Publish schemas, descriptions, glossary, lineage and the expert operating "
        "guidance. `blindcity run` does this too; use this to publish without playing a scenario.",
    )
    p_emit.add_argument("--gms", default=config.DATAHUB_GMS_URL, help="DataHub GMS base URL.")
    p_emit.add_argument(
        "--baseline",
        action="store_true",
        help="Emit the control catalog: opaque table names, no descriptions, glossary or lineage.",
    )
    p_emit.add_argument(
        "--check",
        action="store_true",
        help="Publish nothing; report how DataHub differs from this commit's snapshot.",
    )
    p_emit.add_argument("--dump-lineage", metavar="PATH", help="Write the lineage graph as JSON.")
    p_emit.add_argument("--dump-only", action="store_true", help="With --dump-lineage, skip GMS.")
    p_emit.add_argument(
        "--evaluate-assertions",
        action="store_true",
        help="Run the assertions as SQL and publish pass/fail alongside the metadata.",
    )
    p_emit.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Evaluate and print; never contact GMS. Exits 2 on failure, so CI can gate on it.",
    )
    p_emit.add_argument("--run-id", type=int, help="Evaluate against this run. Default: latest.")
    p_emit.add_argument(
        "--all-runs",
        action="store_true",
        help="Evaluate across every run. Row-count assertions stop meaning much this way.",
    )
    _add_overwrite(p_emit)

    # --- run --------------------------------------------------------------------------------
    from blindcity.agent.run import ALL_MODES

    p_run = sub.add_parser(
        "run",
        help="Play one benchmark mode.",
        description="Play one mode of the infrastructure-crisis scenario. Publishes the catalog "
        "first so the metadata matches the commit. For repeats, loop this in bash.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument(
        "--mode",
        choices=list(ALL_MODES),
        default="agent_datahub",
        help="'agent_raw' is the control: same model, prompt, seed, tool budget and SQL access, "
        "with only the catalog removed. 'agent_datahub_live' adds the catalog's assertions, "
        "evaluated each turn. 'agent_analytics' hands the analysis to DataHub's own Analytics "
        "Agent. 'good_policy' and 'bad_policy' are fixed reference lever sets -- no model, no "
        "cost -- that show the scenario is winnable and losable.",
    )
    p_run.add_argument(
        "--model",
        default=None,
        help="Model id. Defaults to $LLM_MODEL. Every mode must use the same one -- that is a "
        "fairness requirement, not a preference.",
    )
    p_run.add_argument("--out", default=None, help="Write the run result JSON here.")
    p_run.add_argument("--gms", default=config.DATAHUB_GMS_URL, help="DataHub GMS base URL.")
    p_run.add_argument(
        "--turns", type=int, default=None, help="Truncate the scenario, for smoke tests."
    )
    p_run.add_argument(
        "--tool-budget",
        type=int,
        default=None,
        help="Tool calls the model may make per turn before it must commit.",
    )
    p_run.add_argument(
        "--advisor-url",
        default=None,
        help="Base URL of a running Analytics Agent, for --mode agent_analytics.",
    )
    p_run.add_argument(
        "--transcript",
        default=None,
        help="Write every exchange with the model here. Defaults to <out>.transcript.jsonl. The "
        "only artifact that can settle what a mode could actually see.",
    )
    p_run.add_argument(
        "--keep-views", action="store_true", help="Leave the per-run SQL views for inspection."
    )
    p_run.add_argument(
        "--keep-warehouse",
        action="store_true",
        help="Append to the existing warehouse instead of clearing it. The default is a clean "
        "slate, so no run inherits another's rows, planner statistics or leftover views.",
    )
    p_run.add_argument(
        "--force-clean",
        action="store_true",
        help="Clear the warehouse even when another run looks like it is still playing. This "
        "deletes that run's data; only use it when you know the process is dead.",
    )
    _add_overwrite(p_run)

    # --- compare ----------------------------------------------------------------------------
    p_cmp = sub.add_parser(
        "compare",
        help="Summarise result files into one table.",
        description="Read run results off disk and print the comparison. Runs nothing, costs "
        "nothing, needs no database.",
    )
    p_cmp.add_argument(
        "results",
        nargs="+",
        metavar="GLOB",
        help='Result files or globs, e.g. "results/*.json". Quote them so the shell does not '
        "expand them first.",
    )
    p_cmp.add_argument("--out", default=None, help="Write the markdown table here as well.")
    p_cmp.add_argument("--model", default=None, help="Model label for the header, if not in the runs.")

    return parser


def main() -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 2

    from blindcity.commands import compare, emit, run, sim

    handlers = {"sim": sim.run, "emit": emit.run, "run": run.run, "compare": compare.run}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
