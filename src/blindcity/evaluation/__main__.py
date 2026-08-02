"""Entry point for `uv run eval`."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval", description="Run the context A/B evaluation.")
    parser.add_argument("--seeds", type=int, default=5, help="Number of seeds to run each arm on.")
    parser.add_argument("--years", type=int, default=20, help="Simulated years per run.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(f"eval: not implemented (seeds={args.seeds}, years={args.years})")
    print("Next step: TASKS.md Slice 8 — build the harness. A human runs the scored evaluation (H3).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
