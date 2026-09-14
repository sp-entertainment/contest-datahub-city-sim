"""`blindcity emit` — publish the catalog snapshot to DataHub, and check what is published.

`blindcity run` applies the catalog too, so this command exists for the times you want to publish
without playing a scenario: setting a machine up, re-publishing after editing a band, or inspecting
what DataHub currently holds with `--check`.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def run(args: Any) -> int:
    from blindcity.catalog.apply import apply_catalog
    from blindcity.catalog.emit import lineage_graph_dict

    if args.check:
        return _check(args.gms)

    if args.dump_lineage:
        graph = lineage_graph_dict()
        with open(args.dump_lineage, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2)
        print(f"emit: wrote {graph['edge_count']} edges to {args.dump_lineage}")
        print(f"emit: tax->revenue direct edges: {len(graph.get('tax_to_revenue') or [])}")
        if args.dump_only:
            return 0

    assertion_results = None
    if args.evaluate_assertions or args.evaluate_only:
        try:
            assertion_results, scope = _evaluate(args.run_id, all_runs=args.all_runs)
        except Exception as exc:  # noqa: BLE001 — CLI surface
            print(f"emit: assertion evaluation failed: {exc}", file=sys.stderr)
            return 1
        passed = sum(1 for r in assertion_results if r.passed)
        where = "all runs" if scope is None else f"run_id={scope}"
        print(f"emit: assertions evaluated {passed}/{len(assertion_results)} passed ({where})")
        for r in assertion_results:
            print(f"  {'PASS' if r.passed else 'FAIL'} {r.table}.{r.column}: {r.detail}")
        if args.evaluate_only:
            # Non-zero on failure so this can gate CI: an assertion that fails is the warehouse
            # disagreeing with its own documentation, which is worth stopping for.
            return 0 if passed == len(assertion_results) else 2

    try:
        applied, result, drift = apply_catalog(
            args.gms,
            overwrite=args.overwrite_datahub,
            baseline=args.baseline,
            assertion_results=assertion_results if not args.baseline else None,
        )
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"emit: {exc}", file=sys.stderr)
        return 1

    if not applied:
        print("emit: nothing published; DataHub keeps its current values.")
        return 0

    assert result is not None
    if drift and not drift.empty:
        print(f"emit: replaced {len(drift.lines())} value(s) that differed in DataHub.")
    print(
        f"emit: mode={result.mode} tables={len(result.tables)} glossary={result.glossary_terms} "
        f"lineage_edges={result.lineage_edges} assertions={result.assertions}"
    )
    if result.mode == "full":
        print(
            "emit: view lineage in the DataHub UI at http://localhost:9002 — search dataset "
            "'budget_monthly', open the Lineage tab. Upstream should include lever_monthly."
        )
    return 0


def _check(gms: str) -> int:
    """Report how DataHub differs from this commit's snapshot. Publishes nothing.

    A diagnostic, not a gate on anything else: DataHub is the authoritative copy at run time, so a
    difference is a question for a person ("did I mean to edit that?"), not an error in itself.
    """
    from blindcity.catalog.apply import catalog_drift

    try:
        drift = catalog_drift(gms)
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"emit: {exc}", file=sys.stderr)
        return 1

    if drift.empty:
        print(f"emit: DataHub at {gms} holds no City Sim catalog. Publish it with `blindcity emit`.")
        return 1
    if not drift:
        print("emit: DataHub matches this commit's catalog snapshot.")
        return 0

    print(f"emit: DataHub differs from the snapshot ({len(drift.lines())} item(s)):")
    for line in drift.lines()[:40]:
        print(line[:300])
    print("emit: re-publish with `blindcity emit --overwrite-datahub true`.")
    return 1


def _evaluate(run_id: int | None = None, *, all_runs: bool = False):
    """Evaluate assertions, by default against the most recent simulation run.

    The warehouse appends, so an unscoped assertion pools every run ever loaded — which makes the
    row-count assertions easier on every load and mixes benchmark modes that exist to be compared.
    `--all-runs` opts into the unscoped behaviour deliberately.
    """
    from blindcity.catalog.assertions import evaluate_assertions, latest_run_id
    from blindcity.sim.warehouse import connect, ensure_schema

    conn = connect()
    try:
        ensure_schema(conn)
        scope = None if all_runs else (run_id if run_id is not None else latest_run_id(conn))
        if scope is None and not all_runs:
            print(
                "emit: warehouse has no runs — load one with `blindcity sim` first.",
                file=sys.stderr,
            )
        return evaluate_assertions(conn, run_id=scope), scope
    finally:
        conn.close()
