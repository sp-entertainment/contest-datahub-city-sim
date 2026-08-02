"""Entry point for `uv run sim`."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sim", description="Run the Blind City simulation.")
    parser.add_argument("--seed", type=int, default=42, help="Seed. Same seed, same city, always.")
    parser.add_argument("--years", type=int, default=20, help="Simulated years to run.")
    parser.add_argument("--serve", action="store_true", help="Expose the FastAPI control surface.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(f"sim: not implemented (seed={args.seed}, years={args.years}, serve={args.serve})")
    print("Next step: TASKS.md Slice 1 — tick loop, citizens, budget, Postgres writes.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
