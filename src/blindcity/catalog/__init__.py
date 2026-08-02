"""Metadata emission into DataHub: schemas, glossary terms, generated lineage, assertions.

Named `catalog` rather than `datahub` on purpose — a top-level `datahub` package would shadow the
installed `acryl-datahub` module and break every import of the DataHub SDK.

Lineage is generated from the simulation's equations, never hand-authored (docs/DECISIONS.md).

Plan: TASKS.md Day 4.
"""
