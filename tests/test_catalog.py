"""Catalog generation tests — lineage must come from the sim causal graph."""

from __future__ import annotations

from blindcity.catalog.emit import lineage_graph_dict
from blindcity.catalog.schema_spec import GLOSSARY_TERMS, TABLES
from blindcity.sim.causal import CAUSAL_EDGES, tax_to_revenue_path


def test_lineage_generated_from_causal_edges():
    graph = lineage_graph_dict()
    assert graph["generated_from"] == "blindcity.sim.causal.CAUSAL_EDGES"
    assert graph["edge_count"] == len(CAUSAL_EDGES)
    assert graph["edge_count"] > 0


def test_tax_rate_to_revenue_edge_exists():
    path = tax_to_revenue_path()
    assert path, "expected a causal path from tax rate toward revenue"
    direct = [
        e
        for e in CAUSAL_EDGES
        if e.column_source == "income_tax_rate" and e.column_target == "income_tax_revenue"
    ]
    assert direct, "direct income_tax_rate → income_tax_revenue edge required"
    graph = lineage_graph_dict()
    assert graph["tax_to_revenue"], "lineage dump must expose tax→revenue edges"


def test_full_schema_has_descriptions():
    for table in TABLES:
        assert table.description
        assert table.baseline_name
        assert table.baseline_name != table.name
        for col in table.columns:
            assert col.name
            assert col.description


def test_glossary_covers_core_concepts():
    names = {n for n, _, _ in GLOSSARY_TERMS}
    for required in (
        "IncomeTaxRate",
        "IncomeTaxRevenue",
        "CitizenSatisfaction",
        "Migration",
        "RoadWear",
    ):
        assert required in names


def test_baseline_names_are_realistic_not_identical():
    full = {t.name for t in TABLES}
    base = {t.baseline_name for t in TABLES}
    assert full.isdisjoint(base)
    assert len(base) == len(TABLES)
