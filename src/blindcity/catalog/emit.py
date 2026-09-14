"""Emit City Sim metadata into DataHub via the REST emitter.

Full mode: schemas + descriptions + glossary + generated lineage + assertions.
Baseline mode (`--baseline`): schemas only, realistic opaque table names, no descriptions,
no glossary, no lineage — the honest A/B control catalog.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from blindcity.catalog.schema_spec import (
    ASSERTIONS,
    GLOSSARY_TERMS,
    TABLES,
    TERM_COLUMNS,
    TableSpec,
)
from blindcity.sim.causal import CAUSAL_EDGES

PLATFORM = "postgres"
ENV = "PROD"
DEFAULT_DB = "blindcity"
DEFAULT_SCHEMA = "public"


def dataset_urn(table: str, platform: str = PLATFORM, env: str = ENV) -> str:
    # DataHub dataset urn: urn:li:dataset:(urn:li:dataPlatform:postgres,db.schema.table,PROD)
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{DEFAULT_DB}.{DEFAULT_SCHEMA}.{table},{env})"


def glossary_term_urn(name: str) -> str:
    return f"urn:li:glossaryTerm:blindcity.{name}"


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class EmitResult:
    mode: str
    entities_emitted: int
    lineage_edges: int
    glossary_terms: int
    assertions: int
    tables: list[str]


def _post_gms(gms: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    url = gms.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GMS {path} failed HTTP {e.code}: {detail}") from e


def _emit_mcp(gms: str, entity_urn: str, aspect_name: str, aspect: dict[str, Any]) -> None:
    """Emit a single MCP via /aspects?action=ingestProposal (OSS quickstart)."""
    proposal = {
        "proposal": {
            "entityType": _entity_type(entity_urn),
            "entityUrn": entity_urn,
            "changeType": "UPSERT",
            "aspectName": aspect_name,
            "aspect": {
                "contentType": "application/json",
                "value": json.dumps(aspect),
            },
        }
    }
    _post_gms(gms, "/aspects?action=ingestProposal", proposal)


def _entity_type(urn: str) -> str:
    # urn:li:dataset:(...) or urn:li:glossaryTerm:...
    rest = urn[len("urn:li:") :]
    return rest.split(":", 1)[0].split("(", 1)[0]


def _schema_metadata(table: TableSpec, *, include_descriptions: bool) -> dict[str, Any]:
    fields = []
    for col in table.columns:
        fields.append(
            {
                "fieldPath": col.name,
                "nativeDataType": col.native_type,
                "type": {"type": {"com.linkedin.schema.StringType": {}}},
                "description": col.description if include_descriptions else "",
                "recursive": False,
                "nullable": True,
            }
        )
    return {
        "schemaName": table.name,
        "platform": f"urn:li:dataPlatform:{PLATFORM}",
        "version": 0,
        "fields": fields,
        "platformSchema": {
            "com.linkedin.schema.OtherSchema": {
                "rawSchema": json.dumps(
                    {c.name: c.native_type for c in table.columns}
                )
            }
        },
        "hash": "",
        "cluster": "",
    }


def _dataset_properties(table: TableSpec, *, include_descriptions: bool) -> dict[str, Any]:
    return {
        "name": table.name,
        "description": table.description if include_descriptions else "",
        "customProperties": {
            "platform": PLATFORM,
            "database": DEFAULT_DB,
            "schema": DEFAULT_SCHEMA,
        },
    }


def _status_aspect() -> dict[str, Any]:
    return {"removed": False}


def emit_glossary(gms: str) -> int:
    count = 0
    for name, display, definition in GLOSSARY_TERMS:
        urn = glossary_term_urn(name)
        info = {
            "name": display,
            "definition": definition,
            "termSource": "INTERNAL",
        }
        _emit_mcp(gms, urn, "glossaryTermInfo", info)
        _emit_mcp(gms, urn, "status", _status_aspect())
        count += 1
    return count


def emit_term_links(gms: str) -> int:
    """Attach each glossary term to the dataset whose column it defines.

    A term entity on its own is unreachable: `dataset(urn) { glossaryTerms }` returns nothing, so
    the whole glossary was invisible to anything reading the catalog through a dataset -- which is
    every consumer we have, including the agent. Twenty terms were emitted and none were delivered.
    """
    by_table: dict[str, list[tuple[str, str]]] = {}
    for term, table, column in TERM_COLUMNS:
        by_table.setdefault(table, []).append((term, column))

    linked = 0
    for table, entries in by_table.items():
        associations = [
            {"urn": glossary_term_urn(term), "context": column} for term, column in entries
        ]
        _emit_mcp(
            gms,
            dataset_urn(table),
            "glossaryTerms",
            {
                "terms": associations,
                # Required by the GlossaryTerms schema; GMS rejects the aspect with a 422 without
                # it, unlike most aspects which default it.
                "auditStamp": {
                    "time": int(time.time() * 1000),
                    "actor": "urn:li:corpuser:datahub",
                },
            },
        )
        linked += len(associations)
    return linked


def emit_tables(gms: str, *, baseline: bool) -> list[str]:
    names: list[str] = []
    for table in TABLES:
        emit_name = table.baseline_name if baseline else table.name
        # Build a TableSpec-like view with the emission name
        view = TableSpec(
            name=emit_name,
            description=table.description,
            columns=table.columns,
            baseline_name=table.baseline_name,
        )
        urn = dataset_urn(emit_name)
        _emit_mcp(gms, urn, "status", _status_aspect())
        _emit_mcp(
            gms,
            urn,
            "datasetProperties",
            _dataset_properties(view, include_descriptions=not baseline),
        )
        _emit_mcp(
            gms,
            urn,
            "schemaMetadata",
            _schema_metadata(view, include_descriptions=not baseline),
        )
        names.append(emit_name)
    return names


def emit_lineage(gms: str) -> int:
    """Generate table- and column-level lineage from CAUSAL_EDGES — not hand-authored MCPs.

    Table-level edges land in `upstreamLineage` (queryable in the UI Lineage tab). Column-level
    edges are attached as `fineGrainedLineages` on the same aspect when GMS accepts them; the
    causal edge list is always the source of truth regardless.

    Every edge emitted here is validated against the running simulation by
    `blindcity.sim.causal_check` — nothing reaches the catalog that cannot be demonstrated.
    """
    # Group column edges by destination table so one aspect write holds all upstreams.
    by_dst: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for edge in CAUSAL_EDGES:
        by_dst.setdefault(edge.table_target, {}).setdefault(edge.table_source, []).append(
            (edge.column_source, edge.column_target)
        )

    edge_count = 0
    for dst_table, sources in by_dst.items():
        dst_urn = dataset_urn(dst_table)
        upstreams = []
        fine_grained = []
        for src_table in sorted(sources):
            src_urn = dataset_urn(src_table)
            cols = sources[src_table]
            upstreams.append(
                {
                    "dataset": src_urn,
                    "type": "TRANSFORMED",
                    "auditStamp": {
                        "time": _now_ms(),
                        "actor": "urn:li:corpuser:datahub",
                    },
                }
            )
            for sc, tc in cols:
                edge_count += 1
                fine_grained.append(
                    {
                        "upstreamType": "FIELD_SET",
                        "upstreams": [f"urn:li:schemaField:({src_urn},{sc})"],
                        "downstreamType": "FIELD_SET",
                        "downstreams": [f"urn:li:schemaField:({dst_urn},{tc})"],
                        "transformOperation": "SIMULATION_EQUATION",
                        "confidenceScore": 1.0,
                    }
                )

        # Prefer table-level lineage alone first (reliably indexed by the graph service).
        table_aspect = {"upstreams": upstreams}
        _emit_mcp(gms, dst_urn, "upstreamLineage", table_aspect)

        # Best-effort column-level enrichment; ignore failures so table lineage still lands.
        if fine_grained:
            try:
                _emit_mcp(
                    gms,
                    dst_urn,
                    "upstreamLineage",
                    {"upstreams": upstreams, "fineGrainedLineages": fine_grained},
                )
            except RuntimeError:
                pass

    return edge_count


def emit_assertions(
    gms: str,
    *,
    results: list[Any] | None = None,
) -> int:
    """Emit assertion metadata and, when provided, SQL evaluation pass/fail results.

    Declarations alone are not enough — a catalog that never runs its assertions can report
    success while the warehouse is out of range. Pass `results` from
    `blindcity.catalog.assertions.evaluate_assertions` so FAIL is reportable.
    """
    from blindcity.catalog.assertions import AssertionResult, results_as_custom_properties
    from blindcity.catalog.operational import guidance_properties

    count = 0
    by_table: dict[str, list[tuple[str, str]]] = {}
    for table, column, desc in ASSERTIONS:
        by_table.setdefault(table, []).append((column, desc))

    eval_props: dict[str, str] = {}
    if results is not None:
        typed = [r for r in results if isinstance(r, AssertionResult)]
        eval_props = results_as_custom_properties(typed)

    # The expert operating guidance, published here rather than injected into one mode's prompt.
    # This is the delivery half of `catalog/operational.py`: `agent_datahub_live` reads it back out
    # of DataHub at run time and imports none of it.
    guidance = guidance_properties()

    # Guidance and assertions do not cover the same tables -- the lever bands hang off
    # `lever_monthly`, which declares no assertions -- so this iterates the union. Dropping the
    # tables that only carry guidance would silently publish 5 of the 8 lever bands.
    specs = {t.name: t for t in TABLES}
    for table in sorted(set(by_table) | set(guidance)):
        urn = dataset_urn(table)
        items = by_table.get(table, [])
        custom = {f"assertion.{i}.{col}": desc for i, (col, desc) in enumerate(items)}
        # Attach evaluation outcomes that mention this table (and the global summary once).
        for k, v in eval_props.items():
            if f".{table}." in k or k.startswith("assertion_results."):
                custom[k] = v
        custom.update(guidance.get(table, {}))

        # Built on top of the table's own properties rather than replacing them. `datasetProperties`
        # is written whole, so the previous version of this overwrote what `emit_tables` had just
        # published: every table carrying an assertion lost its real description to "Blind City
        # assertions for <table>" and lost its platform/database/schema properties with it. Six of
        # the fourteen tables were affected, and the mode that reads descriptions is the one the
        # headline comparison rests on.
        spec = specs.get(table)
        props = _dataset_properties(spec, include_descriptions=True) if spec else {
            "name": table, "description": ""
        }
        props["customProperties"] = {**props.get("customProperties", {}), **custom}
        _emit_mcp(gms, urn, "datasetProperties", props)
        # Also emit an AssertionInfo-style separate entity when possible
        for i, (col, desc) in enumerate(items):
            assertion_urn = f"urn:li:assertion:blindcity.{table}.{col}.{i}"
            # Look up pass/fail for this assertion if we have results
            run_status = None
            if results is not None:
                for r in results:
                    if (
                        isinstance(r, AssertionResult)
                        and r.table == table
                        and r.column == col
                    ):
                        run_status = "SUCCESS" if r.passed else "FAILURE"
                        break
            info = {
                "type": "DATASET",
                "datasetAssertion": {
                    "dataset": urn,
                    "scope": "DATASET_COLUMN" if col != "*" else "DATASET_ROWS",
                    "aggregation": "IDENTITY",
                    "operator": "BETWEEN" if col != "*" else "GREATER_THAN_OR_EQUAL_TO",
                    "nativeType": "BLINDCITY_RANGE",
                    "nativeParameters": {
                        "description": desc,
                        "column": col,
                        **({"lastResult": run_status} if run_status else {}),
                    },
                    "fields": (
                        [f"urn:li:schemaField:({urn},{col})"] if col != "*" else []
                    ),
                },
                "description": desc
                + (f" [{run_status}]" if run_status else ""),
            }
            try:
                _emit_mcp(gms, assertion_urn, "assertionInfo", info)
                _emit_mcp(gms, assertion_urn, "status", _status_aspect())
                if run_status is not None:
                    # AssertionRunEvent-style property so FAIL is visible without GraphQL.
                    run_props = {
                        "customProperties": {
                            "result": run_status,
                            "evaluated": "true",
                        },
                        "name": f"{table}.{col}",
                        "description": desc,
                    }
                    try:
                        _emit_mcp(gms, assertion_urn, "datasetProperties", run_props)
                    except RuntimeError:
                        pass
                count += 1
            except RuntimeError:
                # Assertion entity type may be picky on some GMS versions; properties still land.
                count += 1
    return count


def emit_all(
    gms: str,
    *,
    baseline: bool = False,
    assertion_results: list[Any] | None = None,
) -> EmitResult:
    tables = emit_tables(gms, baseline=baseline)
    glossary = 0
    lineage = 0
    assertions = 0
    if not baseline:
        glossary = emit_glossary(gms)
        # Terms are useless until something links them to the data they describe.
        emit_term_links(gms)
        lineage = emit_lineage(gms)
        assertions = emit_assertions(gms, results=assertion_results)

    entities = len(tables) + glossary + (assertions if not baseline else 0)
    return EmitResult(
        mode="baseline" if baseline else "full",
        entities_emitted=entities,
        lineage_edges=lineage,
        glossary_terms=glossary,
        assertions=assertions,
        tables=tables,
    )


def lineage_graph_dict() -> dict[str, Any]:
    """Serializable form of the generated lineage graph (for tests and evidence dumps)."""
    edges = [
        {
            "source": e.source,
            "target": e.target,
            "table_source": e.table_source,
            "column_source": e.column_source,
            "table_target": e.table_target,
            "column_target": e.column_target,
            "description": e.description,
        }
        for e in CAUSAL_EDGES
    ]
    return {
        "generated_from": "blindcity.sim.causal.CAUSAL_EDGES",
        "edge_count": len(edges),
        "edges": edges,
        "tax_to_revenue": [
            e
            for e in edges
            if e["column_source"] == "income_tax_rate"
            and e["column_target"] == "income_tax_revenue"
        ],
    }
