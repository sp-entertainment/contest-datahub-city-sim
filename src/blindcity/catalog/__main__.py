"""Entry point for `uv run datahub-emit`."""

from __future__ import annotations

import argparse
import sys

from blindcity import config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datahub-emit", description="Emit Blind City metadata into DataHub."
    )
    parser.add_argument("--gms", default=config.DATAHUB_GMS_URL, help="DataHub GMS base URL.")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Emit the stripped control catalog used by the A/B evaluation: schemas only, "
        "no descriptions, no glossary, no lineage.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(f"datahub-emit: not implemented (gms={args.gms}, baseline={args.baseline})")
    print("Next step: TASKS.md Slice 3 — schema ingestion, glossary, generated lineage, assertions.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
