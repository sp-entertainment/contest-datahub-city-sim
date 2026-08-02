"""Entry point for `uv run datahub-emit`."""

from __future__ import annotations

import argparse
import json
import sys

from blindcity import config
from blindcity.catalog.emit import emit_all, lineage_graph_dict


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
    parser.add_argument(
        "--dump-lineage",
        metavar="PATH",
        help="Write the generated lineage graph JSON to PATH (no GMS required).",
    )
    parser.add_argument(
        "--dump-only",
        action="store_true",
        help="With --dump-lineage, skip GMS emission entirely.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.dump_lineage:
        graph = lineage_graph_dict()
        with open(args.dump_lineage, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2)
        print(f"datahub-emit: wrote {graph['edge_count']} edges to {args.dump_lineage}")
        tax = graph.get("tax_to_revenue") or []
        print(f"datahub-emit: tax→revenue direct edges: {len(tax)}")
        if args.dump_only:
            return 0

    try:
        result = emit_all(args.gms, baseline=args.baseline)
    except Exception as exc:  # noqa: BLE001
        print(f"datahub-emit: failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"datahub-emit: mode={result.mode} tables={len(result.tables)} "
        f"glossary={result.glossary_terms} lineage_edges={result.lineage_edges} "
        f"assertions={result.assertions}"
    )
    print(f"datahub-emit: tables={', '.join(result.tables)}")
    if result.mode == "full":
        ui = args.gms.replace(":8080", ":9002").rstrip("/")
        if ui.endswith("8080"):
            ui = ui[:-4] + "9002"
        print(
            "datahub-emit: view lineage in the DataHub UI at http://localhost:9002 — "
            "search dataset 'budget_monthly', open the Lineage tab. "
            "Upstream should include lever_monthly (income_tax_rate → income_tax_revenue)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
