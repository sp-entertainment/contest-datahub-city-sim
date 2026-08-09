"""The agent records what it learned back into the catalog.

The point is not decoration. A data catalog rots because the people who discover things about a
dataset — that a column is useless, that a table is where you actually look for X — discover it
in a query window and never write it down. An agent that queries a warehouse and keeps its
findings to itself has the same failure mode, at machine speed.

So after a run, each dataset the agent actually queried gets a note saying which run touched it,
how often, and what the agent concluded. The next reader of that dataset — human or agent — sees
it in DataHub.

**Only `agent_datahub` writes back.** `agent_raw` has no catalog by construction; giving the
control mode a write path would be a second difference between the modes and would invalidate the
headline result. Write-back happens after the run is scored, so it cannot affect the score
either way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from blindcity import config
from blindcity.catalog.emit import _emit_mcp, dataset_urn
from blindcity.catalog.schema_spec import TABLES

_KNOWN_TABLES = {t.name for t in TABLES}
# Matches a bare or schema-qualified table name after FROM or JOIN.
_TABLE_REF = re.compile(r"\b(?:from|join)\s+(?:[a-zA-Z_][\w]*\.)?([a-zA-Z_][\w]*)", re.IGNORECASE)


@dataclass
class WriteBackResult:
    datasets: int
    tables: list[str]
    skipped: str | None = None
    failures: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "datasets": self.datasets,
            "tables": self.tables,
            "skipped": self.skipped,
            "failures": self.failures,
        }


def tables_queried(queries: list[str]) -> dict[str, int]:
    """Count how often each known warehouse table appeared in the agent's SQL.

    Names are matched against the schema rather than trusted from the text, so a typo, a CTE
    alias, or an `information_schema` probe never becomes a dataset URN that does not exist.
    """
    counts: dict[str, int] = {}
    for query in queries:
        for name in set(_TABLE_REF.findall(query or "")):
            lowered = name.lower()
            if lowered in _KNOWN_TABLES:
                counts[lowered] = counts.get(lowered, 0) + 1
    return counts


def _note(mode: str, run_id: str, hits: int, rationale: str) -> dict[str, str]:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    note = {
        f"agent_finding.{run_id}.mode": mode,
        f"agent_finding.{run_id}.queried_times": str(hits),
        f"agent_finding.{run_id}.at": stamp,
    }
    if rationale:
        note[f"agent_finding.{run_id}.conclusion"] = rationale[:900]
    return note


def write_back(
    report: dict[str, Any],
    run_id: str,
    *,
    gms_url: str | None = None,
) -> WriteBackResult:
    """Attach the agent's findings to the datasets it queried.

    Returns what was written. Never raises into the caller: a catalog that is down must not
    invalidate a completed run, and the run's own result is the evidence, not this.
    """
    if report.get("catalog") != "datahub":
        return WriteBackResult(0, [], skipped="control mode has no catalog by construction")

    gms = (gms_url or config.DATAHUB_GMS_URL).rstrip("/")
    turns = report.get("turns") or []
    queries = [q for turn in turns for q in (turn.get("queries") or [])]
    counts = tables_queried(queries)
    if not counts:
        return WriteBackResult(0, [], skipped="agent queried no catalogued table")

    # The last stated rationale is the agent's settled view of the city, after it has seen the
    # consequences of its earlier turns.
    rationale = ""
    for turn in reversed(turns):
        if turn.get("rationale"):
            rationale = turn["rationale"]
            break

    mode = report.get("controller", "agent")
    written: list[str] = []
    failed: dict[str, str] = {}
    with httpx.Client(timeout=30.0) as client:
        for table, hits in sorted(counts.items()):
            urn = dataset_urn(table)
            try:
                existing = _current_properties(client, gms, urn)
                # UPSERT replaces the whole aspect, so the description and any earlier findings
                # have to be carried forward. Writing only the new keys would strip the table
                # and column documentation — the very thing agent_datahub depends on, degraded
                # a little further by every run.
                merged = dict(existing.get("customProperties") or {})
                merged.update(_note(mode, run_id, hits, rationale))
                aspect: dict[str, Any] = {"customProperties": merged}
                if existing.get("description"):
                    aspect["description"] = existing["description"]
                if existing.get("name"):
                    aspect["name"] = existing["name"]
                _emit_mcp(gms, urn, "datasetProperties", aspect)
                written.append(table)
            except Exception as exc:  # noqa: BLE001 - a down catalog must not fail a scored run
                # Recorded rather than swallowed. Write-back failing is not fatal to the run, but
                # it is not nothing either: a silent skip here looks identical to an agent that
                # found nothing worth writing.
                failed[table] = str(exc)[:200]

    return WriteBackResult(len(written), written, failures=failed)


_PROPS_QUERY = """
query($urn: String!) {
  dataset(urn: $urn) {
    properties { name description customProperties { key value } }
  }
}
"""


def _current_properties(client: httpx.Client, gms: str, urn: str) -> dict[str, Any]:
    """Read the dataset's existing properties so an UPSERT does not destroy them."""
    r = client.post(
        f"{gms}/api/graphql", json={"query": _PROPS_QUERY, "variables": {"urn": urn}}
    )
    if r.status_code != 200:
        raise RuntimeError(f"GMS properties read failed: HTTP {r.status_code}")
    dataset = ((r.json() or {}).get("data") or {}).get("dataset") or {}
    props = dataset.get("properties") or {}
    return {
        "name": props.get("name"),
        "description": props.get("description"),
        "customProperties": {
            entry["key"]: entry["value"] for entry in (props.get("customProperties") or [])
        },
    }
