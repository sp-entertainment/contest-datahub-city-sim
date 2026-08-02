"""Metadata emission into DataHub: schemas, glossary terms, generated lineage, assertions.

Named `catalog` rather than `datahub` on purpose — a top-level `datahub` package would shadow the
installed `acryl-datahub` module and break every import of the DataHub SDK.

Lineage is generated from `blindcity.sim.causal.CAUSAL_EDGES`, never hand-written here, and every
edge in that list is validated against the running simulation by `blindcity.sim.causal_check`
(docs/DECISIONS.md).

Plan: TASKS.md, Slice 3.
"""
