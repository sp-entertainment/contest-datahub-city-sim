"""Entry point for `uv run datahub-emit`."""

from __future__ import annotations

import argparse
import json
import sys

from blindcity import config
from blindcity.catalog.emit import emit_all, lineage_graph_dict
from blindcity.console import configure_console


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
    parser.add_argument(
        "--evaluate-assertions",
        action="store_true",
        help="Run each catalog assertion as SQL against the warehouse and emit pass/fail. "
        "Also usable alone with --evaluate-only (no GMS write).",
    )
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Evaluate assertions against Postgres and print results; do not call GMS.",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Evaluate assertions against this simulation run. Defaults to the most recent.",
    )
    parser.add_argument(
        "--all-runs",
        action="store_true",
        help="Evaluate across every run in the warehouse instead of one. Row-count assertions "
        "are not meaningful this way once more than one run is loaded.",
    )
    parser.add_argument(
        "--check-guidance",
        action="store_true",
        help="Emit nothing. Compare the operating guidance published in DataHub against what "
        "catalog/operational.py authors, and exit non-zero on any difference. The agent reads "
        "the published copy, so drift between the two is the catalog steering a run with a band "
        "nobody reviewed.",
    )
    return parser


def _check_guidance(gms: str) -> int:
    """Fail when DataHub's guidance is not what this repository authors.

    The point of publishing the guidance is that the agent reads DataHub rather than the source,
    which necessarily makes them two copies. This is the guard that keeps them one thing: it
    re-derives the published form from source and diffs it against what GMS actually returns.
    """
    from blindcity.agent.guidance import GuidanceUnavailable, fetch_guidance
    from blindcity.catalog.operational import (
        LEVER_GUIDANCE,
        OUTCOME_ASSERTIONS,
        RESPONSE_LAGS,
    )

    try:
        published = fetch_guidance(gms)
    except GuidanceUnavailable as exc:
        print(f"datahub-emit: {exc}", file=sys.stderr)
        return 1

    drift = []
    for label, want, got in (
        ("lever", LEVER_GUIDANCE, published.levers),
        ("outcome", OUTCOME_ASSERTIONS, published.outcomes),
        ("lag", RESPONSE_LAGS, published.lags),
    ):
        missing = [w for w in want if w not in got]
        extra = [g for g in got if g not in want]
        for m in missing:
            drift.append(f"  {label}: not published as authored -> {m}")
        for e in extra:
            drift.append(f"  {label}: published but not authored here -> {e}")

    if drift:
        print(
            f"datahub-emit: DataHub guidance differs from catalog/operational.py "
            f"({len(drift)} difference(s)):",
            file=sys.stderr,
        )
        for line in drift[:20]:
            print(line[:300], file=sys.stderr)
        print("datahub-emit: re-publish with `uv run datahub-emit`.", file=sys.stderr)
        return 1

    print(
        f"datahub-emit: guidance in DataHub matches source "
        f"({len(published.levers)} levers, {len(published.outcomes)} outcomes, "
        f"{len(published.lags)} response lags)"
    )
    return 0


def _evaluate_warehouse(run_id: int | None = None, *, all_runs: bool = False):
    """Evaluate assertions, by default against the most recent simulation run.

    The warehouse appends, so an unscoped assertion pools every run ever loaded — which makes
    the row-count assertions easier on every load and mixes benchmark modes that exist to be
    compared. `--all-runs` opts into the unscoped behaviour deliberately.
    """
    from blindcity.catalog.assertions import evaluate_assertions, latest_run_id
    from blindcity.sim.warehouse import connect, ensure_schema

    conn = connect()
    try:
        ensure_schema(conn)
        scope = None if all_runs else (run_id if run_id is not None else latest_run_id(conn))
        if scope is None and not all_runs:
            print(
                "datahub-emit: warehouse has no runs — load one with `uv run sim` first.",
                file=sys.stderr,
            )
        return evaluate_assertions(conn, run_id=scope), scope
    finally:
        conn.close()


def main() -> int:
    configure_console()
    args = build_parser().parse_args()

    if args.check_guidance:
        return _check_guidance(args.gms)

    if args.dump_lineage:
        graph = lineage_graph_dict()
        with open(args.dump_lineage, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2)
        print(f"datahub-emit: wrote {graph['edge_count']} edges to {args.dump_lineage}")
        tax = graph.get("tax_to_revenue") or []
        print(f"datahub-emit: tax→revenue direct edges: {len(tax)}")
        if args.dump_only:
            return 0

    assertion_results = None
    if args.evaluate_assertions or args.evaluate_only:
        try:
            assertion_results, scope = _evaluate_warehouse(args.run_id, all_runs=args.all_runs)
        except Exception as exc:  # noqa: BLE001
            print(f"datahub-emit: assertion evaluation failed: {exc}", file=sys.stderr)
            return 1
        n_pass = sum(1 for r in assertion_results if r.passed)
        where = "all runs" if scope is None else f"run_id={scope}"
        print(
            f"datahub-emit: assertions evaluated {n_pass}/{len(assertion_results)} passed "
            f"({where})"
        )
        for r in assertion_results:
            flag = "PASS" if r.passed else "FAIL"
            print(f"  [{flag}] {r.table}.{r.column}: {r.detail}")
        if args.evaluate_only:
            # Non-zero exit when any assertion fails so CI can gate on honesty.
            return 0 if all(r.passed for r in assertion_results) else 2

    if args.evaluate_only:
        return 0

    try:
        result = emit_all(
            args.gms,
            baseline=args.baseline,
            assertion_results=assertion_results if not args.baseline else None,
        )
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
        print(
            "datahub-emit: view lineage in the DataHub UI at http://localhost:9002 — "
            "search dataset 'budget_monthly', open the Lineage tab. "
            "Upstream should include lever_monthly (income_tax_rate → income_tax_revenue)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
