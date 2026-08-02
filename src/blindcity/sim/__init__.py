"""Headless deterministic city simulation.

Owns the tick loop, the city model, and the warehouse schema it writes into. Also the source of the
causal graph that `blindcity.catalog` emits as DataHub lineage — the equations here *are* the
lineage, which is why it is generated rather than hand-authored (docs/DECISIONS.md).

Plan: TASKS.md, Slice 1 (simulation core) and Slice 2 (city systems and levers).
"""
