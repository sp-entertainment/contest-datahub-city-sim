"""Entry point for `uv run agent`."""

from __future__ import annotations

import argparse
import sys

from blindcity.console import configure_console


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description="Run the Blind City auto-mode agent.")
    parser.add_argument("--mode", choices=("auto",), default="auto", help="Manual mode is the upstream Analytics Agent, not this program.")
    parser.add_argument("--years", type=int, default=20, help="Simulated years to play.")
    parser.add_argument(
        "--context",
        choices=("datahub", "none"),
        default="datahub",
        help="'none' is the A/B control: same model, prompt, seed, tool budget and SQL access, "
        "with only the DataHub context removed. Keep it honest (AGENTS.md).",
    )
    return parser


def main() -> int:
    configure_console()
    args = build_parser().parse_args()
    print(f"agent: not implemented (mode={args.mode}, years={args.years}, context={args.context})")
    print("Next step: TASKS.md Slice 6 — the closed loop, as the agent_datahub and agent_raw arms.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
