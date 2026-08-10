"""`blindcity compare` — summarise result files into one table. Runs nothing.

Kept separate from `run` on purpose. Comparing is a pure function over files already on disk, so it
costs nothing, needs no database, and can be re-run against any set of results at any time —
including results produced weeks apart, or by someone else. Folding it into the runner is what
produced the second runner this consolidation removed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def run(args: Any) -> int:
    from blindcity.benchmark.health import GREEN_THRESHOLD
    from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS
    from blindcity.evaluation.compare import collect, markdown

    paths = [p for pattern in args.results for p in Path().glob(pattern)]
    # A glob that catches a result also catches its sidecars; `collect` filters again, but doing it
    # here too keeps the "no results matched" message honest.
    paths = [
        p for p in paths
        if not p.name.endswith(".agent.json") and not p.name.endswith(".transcript.jsonl")
    ]
    if not paths:
        print(
            f"compare: no result files matched {args.results}. Quote the pattern so the shell "
            "does not expand it, e.g. compare \"results/*.json\".",
            file=sys.stderr,
        )
        return 1

    summaries = collect(paths)
    if not summaries:
        print("compare: matched files, but none were run results.", file=sys.stderr)
        return 1

    report = markdown(
        summaries,
        threshold=GREEN_THRESHOLD,
        seed=INFRASTRUCTURE_CRISIS.seed,
        model=args.model or "unknown",
    )
    print(report)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        as_json = out.with_suffix(".json")
        as_json.write_text(
            json.dumps({m: s.to_dict() for m, s in summaries.items()}, indent=2), encoding="utf-8"
        )
        print(f"compare: wrote {out} and {as_json}", file=sys.stderr)
    return 0
