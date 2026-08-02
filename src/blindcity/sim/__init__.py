"""Headless deterministic city simulation.

Owns the tick loop, the city model, and the warehouse schema it writes into. Also the source of the
causal graph that `blindcity.catalog` emits as DataHub lineage — the equations here *are* the
lineage, which is why it is generated rather than hand-authored (docs/DECISIONS.md).

Plan: TASKS.md Days 2 and 3.
"""
