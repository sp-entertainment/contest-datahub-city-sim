"""Publish the catalog snapshot to DataHub, without destroying anyone's edits.

`catalog/operational.py` and `schema_spec.py` are the snapshot; DataHub is what the agent actually
reads. Publishing keeps the two in step, and every `blindcity run` does it so a fresh clone works
end to end and a run's metadata matches the commit it was played from.

The complication is that DataHub is editable. Someone can widen a band in the UI to see how the
agent responds -- which is the point of putting the guidance there in the first place -- and a
publish step that blindly overwrote that would make the feature useless. So publishing looks first:

  * nothing published yet, or nothing differs -> write, silently. There is nothing to lose.
  * something differs -> `overwrite` decides. `True` writes, `False` leaves DataHub alone and the
    run proceeds against what is there, `None` asks.

Only the guidance and the dataset descriptions are compared. Both come out of the same
`datasetProperties` aspect that the guidance reader already fetches, so the diff costs nothing
extra. Glossary terms and lineage edges are republished without being compared: they are generated
from `CAUSAL_EDGES` and `GLOSSARY_TERMS` rather than hand-tuned, and nobody edits a lineage edge in
the UI to run an experiment. The prompt says as much, rather than implying the diff is exhaustive.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from blindcity.catalog.emit import EmitResult, emit_all
from blindcity.catalog.operational import (
    LEVER_GUIDANCE,
    OUTCOME_ASSERTIONS,
    RESPONSE_LAGS,
    Guidance,
    parse_guidance,
)
from blindcity.catalog.schema_spec import TABLES

FETCH_TIMEOUT_SECONDS = 30.0


@dataclass
class Drift:
    """How DataHub differs from the snapshot this commit would publish."""

    guidance: list[str] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)
    # Nothing published yet. Distinct from "no differences" because an empty catalog is never
    # something a user meant to keep, so it needs no confirmation before being filled.
    empty: bool = False

    def __bool__(self) -> bool:
        return bool(self.guidance or self.descriptions)

    def lines(self) -> list[str]:
        return [*self.guidance, *self.descriptions]


def _published(gms: str, *, timeout: float = FETCH_TIMEOUT_SECONDS) -> tuple[dict[str, str], dict[str, str]]:
    """Every custom property and every description currently in DataHub, across all tables."""
    import urllib.parse

    from blindcity.agent.guidance import _custom_properties, dataset_urn

    properties: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    with httpx.Client(timeout=timeout) as client:
        for table in TABLES:
            urn = dataset_urn(table.name)
            properties.update(_custom_properties(client, gms, urn))
            r = client.get(
                f"{gms}/aspects/{urllib.parse.quote(urn, safe='')}"
                "?aspect=datasetProperties&version=0"
            )
            if r.status_code != 200:
                continue
            aspect = (r.json().get("aspect") or {}).get(
                "com.linkedin.dataset.DatasetProperties", {}
            )
            descriptions[table.name] = str(aspect.get("description") or "")
    return properties, descriptions


def _guidance_drift(published: Guidance) -> list[str]:
    """Which authored entries are missing from DataHub, and which published ones are unknown here."""
    out: list[str] = []
    for label, want, got in (
        ("lever", LEVER_GUIDANCE, published.levers),
        ("outcome", OUTCOME_ASSERTIONS, published.outcomes),
        ("lag", RESPONSE_LAGS, published.lags),
    ):
        by_key = {_key(g): g for g in got}
        for w in want:
            actual = by_key.get(_key(w))
            if actual is None:
                out.append(f"  {label} {_key(w)}: not in DataHub")
            elif actual != w:
                out.append(f"  {label} {_key(w)}: DataHub {_summary(actual)} | snapshot {_summary(w)}")
        authored = {_key(w) for w in want}
        for g in got:
            if _key(g) not in authored:
                out.append(f"  {label} {_key(g)}: in DataHub only")
    return out


def _key(entry: Any) -> str:
    return getattr(entry, "lever", None) or getattr(entry, "name", None) or entry.column


def _summary(entry: Any) -> str:
    if hasattr(entry, "low"):
        return f"{entry.low:g}-{entry.high:g}"
    return (entry.note[:40] + "...") if len(entry.note) > 40 else entry.note


def catalog_drift(gms: str) -> Drift:
    """Compare what DataHub holds against what this commit would publish."""
    try:
        properties, descriptions = _published(gms)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"could not read the catalog from DataHub at {gms}: {exc}") from exc

    published = parse_guidance(properties)
    if not published and not any(descriptions.values()):
        return Drift(empty=True)

    changed = [
        f"  description {t.name}: DataHub {descriptions.get(t.name, '')[:40]!r} | "
        f"snapshot {t.description[:40]!r}"
        for t in TABLES
        if descriptions.get(t.name, "") and descriptions.get(t.name) != t.description
    ]
    return Drift(guidance=_guidance_drift(published), descriptions=changed)


def guidance_fingerprint(guidance: Guidance) -> str:
    """A stable hash of the guidance a run actually used.

    Once DataHub is editable, a score cannot be interpreted without knowing which bands produced
    it. This goes in the run report so a UI-edited run is self-describing rather than
    indistinguishable from one played on the published snapshot.
    """
    payload = json.dumps(
        {
            "levers": [[g.lever, g.low, g.high, g.impact, g.note] for g in guidance.levers],
            "outcomes": [
                [a.name, a.table, a.column, a.sql, a.low, a.high, a.note]
                for a in guidance.outcomes
            ],
            "lags": [[lag.column, lag.note] for lag in guidance.lags],
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def apply_catalog(
    gms: str,
    *,
    overwrite: bool | None = None,
    baseline: bool = False,
    assertion_results: list[Any] | None = None,
    ask: Any = input,
    log: Any = print,
) -> tuple[bool, EmitResult | None, Drift]:
    """Publish the snapshot unless DataHub holds edits the caller wants to keep.

    Returns `(applied, emit_result, drift)`. `ask` and `log` are injected so the decision can be
    tested without a terminal.
    """
    drift = catalog_drift(gms)

    if drift and not drift.empty and overwrite is not True:
        log(f"catalog: DataHub differs from this commit's snapshot ({len(drift.lines())} item(s)):")
        for line in drift.lines()[:20]:
            log(line[:300])
        if len(drift.lines()) > 20:
            log(f"  ... and {len(drift.lines()) - 20} more")
        log("catalog: applying replaces these and refreshes schemas, glossary and lineage.")

        if overwrite is False:
            log("catalog: --overwrite-datahub false -- leaving DataHub as it is.")
            return False, None, drift

        answer = str(ask("catalog: overwrite DataHub with the snapshot? [y/N] ")).strip().lower()
        if answer not in {"y", "yes"}:
            log("catalog: leaving DataHub as it is; this run uses its values, not the snapshot.")
            return False, None, drift

    result = emit_all(gms, baseline=baseline, assertion_results=assertion_results)
    return True, result, drift
