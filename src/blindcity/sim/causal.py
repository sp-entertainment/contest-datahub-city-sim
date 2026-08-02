"""Causal graph of the simulation.

DataHub lineage is generated from this structure — the emitter never hand-writes an edge.

**This list is declared here, not derived from `systems.py`.** That means it could drift from the
equations, which is precisely the failure this project set out to beat. `causal_check.py` closes
the gap: every edge below is validated by experiment — perturb the source, run the code that
computes the target, require the target to move — and `tests/test_causal_validation.py` fails the
build for any edge that cannot be demonstrated, or any edge left without an experiment.

So the defensible claim is not "the lineage was extracted from the code" but "every lineage edge is
continuously verified against the running simulation" — which is more than most production data
platforms can say about their own lineage. See docs/DECISIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CausalEdge:
    """One directed causal link: source column concept → target column concept."""

    source: str
    target: str
    table_source: str
    column_source: str
    table_target: str
    column_target: str
    description: str = ""


# Fully qualified concept names used in docs and glossary.
# Format of source/target: "domain.field" for readability; table/column are warehouse names.

CAUSAL_EDGES: tuple[CausalEdge, ...] = (
    # Income tax → revenue and household finances
    CausalEdge(
        "levers.income_tax_rate",
        "budget.income_tax_revenue",
        "lever_monthly",
        "income_tax_rate",
        "budget_monthly",
        "income_tax_revenue",
        "Higher income tax rate increases municipal income-tax revenue.",
    ),
    CausalEdge(
        "levers.income_tax_rate",
        "citizens.disposable_income",
        "lever_monthly",
        "income_tax_rate",
        "citizen_monthly",
        "disposable_income",
        "Income tax reduces disposable income.",
    ),
    CausalEdge(
        "citizens.disposable_income",
        "citizens.satisfaction",
        "citizen_monthly",
        "disposable_income",
        "citizen_monthly",
        "satisfaction",
        "Disposable income raises satisfaction.",
    ),
    # Property tax
    CausalEdge(
        "levers.property_tax_rate",
        "budget.property_tax_revenue",
        "lever_monthly",
        "property_tax_rate",
        "budget_monthly",
        "property_tax_revenue",
        "Property tax rate scales assessed-value revenue.",
    ),
    CausalEdge(
        "levers.property_tax_rate",
        "citizens.satisfaction",
        "lever_monthly",
        "property_tax_rate",
        "citizen_monthly",
        "satisfaction",
        "Higher property tax pressure lowers satisfaction.",
    ),
    # Electricity
    CausalEdge(
        "levers.electricity_tariff",
        "budget.utility_revenue",
        "lever_monthly",
        "electricity_tariff",
        "budget_monthly",
        "utility_revenue",
        "Retail tariff scales electricity bill revenue.",
    ),
    CausalEdge(
        "levers.electricity_tariff",
        "citizens.satisfaction",
        "lever_monthly",
        "electricity_tariff",
        "citizen_monthly",
        "satisfaction",
        "Higher electricity prices lower satisfaction.",
    ),
    CausalEdge(
        "levers.power_contract_mode",
        "power.outage_fraction",
        "lever_monthly",
        "power_contract_mode",
        "power_monthly",
        "outage_fraction",
        "Contract mode changes supply reliability.",
    ),
    CausalEdge(
        "power.outage_fraction",
        "buildings.power_served",
        "power_monthly",
        "outage_fraction",
        "building_monthly",
        "power_served",
        "Outages determine which buildings are served.",
    ),
    CausalEdge(
        "buildings.power_served",
        "citizens.satisfaction",
        "building_monthly",
        "power_served",
        "citizen_monthly",
        "satisfaction",
        "Unpowered homes reduce satisfaction.",
    ),
    # Roads
    CausalEdge(
        "levers.road_maintenance_budget",
        "roads.wear",
        "lever_monthly",
        "road_maintenance_budget",
        "road_monthly",
        "wear",
        "Maintenance spend reduces road wear.",
    ),
    CausalEdge(
        "roads.wear",
        "roads.congestion",
        "road_monthly",
        "wear",
        "road_monthly",
        "congestion",
        "Worn roads worsen congestion for a given traffic volume.",
    ),
    CausalEdge(
        "roads.congestion",
        "commute.travel_time",
        "road_monthly",
        "congestion",
        "commute_monthly",
        "travel_time",
        "Congestion increases commute travel time.",
    ),
    CausalEdge(
        "commute.travel_time",
        "citizens.satisfaction",
        "commute_monthly",
        "travel_time",
        "citizen_monthly",
        "satisfaction",
        "Longer commutes reduce satisfaction.",
    ),
    # Water / sewer
    CausalEdge(
        "levers.water_sewer_capex",
        "water.capacity",
        "lever_monthly",
        "water_sewer_capex",
        "water_monthly",
        "capacity",
        "Capex expands water and sewer capacity.",
    ),
    CausalEdge(
        "water.capacity",
        "water.load_ratio",
        "water_monthly",
        "capacity",
        "water_monthly",
        "load_ratio",
        "Capacity and demand set the load ratio.",
    ),
    CausalEdge(
        "water.load_ratio",
        "citizens.satisfaction",
        "water_monthly",
        "load_ratio",
        "citizen_monthly",
        "satisfaction",
        "Overloaded water/sewer reduces satisfaction.",
    ),
    # Transit
    CausalEdge(
        "levers.transit_fare",
        "budget.transit_revenue",
        "lever_monthly",
        "transit_fare",
        "budget_monthly",
        "transit_revenue",
        "Fare times ridership yields transit revenue.",
    ),
    CausalEdge(
        "levers.transit_fare",
        "citizens.satisfaction",
        "lever_monthly",
        "transit_fare",
        "citizen_monthly",
        "satisfaction",
        "Higher fares lower satisfaction for transit users.",
    ),
    # Zoning
    CausalEdge(
        "levers.zoning_release",
        "tiles.zoning",
        "lever_monthly",
        "zoning_release",
        "tiles",
        "zoning",
        "Zoning release opens undeveloped land for development.",
    ),
    CausalEdge(
        "tiles.zoning",
        "buildings.count",
        "tiles",
        "zoning",
        "buildings",
        "building_id",
        "Zoned land enables new buildings.",
    ),
    # Satisfaction → migration → population → tax base
    CausalEdge(
        "citizens.satisfaction",
        "migration.net",
        "citizen_monthly",
        "satisfaction",
        "migration_monthly",
        "net",
        "Average satisfaction drives household arrivals and departures.",
    ),
    CausalEdge(
        "migration.net",
        "citizens.population",
        "migration_monthly",
        "net",
        "citizen_monthly",
        "citizen_id",
        "Net migration changes population.",
    ),
    CausalEdge(
        "citizens.population",
        "budget.income_tax_revenue",
        "citizen_monthly",
        "citizen_id",
        "budget_monthly",
        "income_tax_revenue",
        "Larger employed population expands the income-tax base.",
    ),
    CausalEdge(
        "citizens.income",
        "budget.income_tax_revenue",
        "citizen_monthly",
        "income",
        "budget_monthly",
        "income_tax_revenue",
        "Household income is the income-tax base.",
    ),
    # Budget balance
    CausalEdge(
        "budget.income_tax_revenue",
        "budget.balance",
        "budget_monthly",
        "income_tax_revenue",
        "budget_monthly",
        "balance",
        "Revenue lines feed the municipal balance.",
    ),
    CausalEdge(
        "budget.property_tax_revenue",
        "budget.balance",
        "budget_monthly",
        "property_tax_revenue",
        "budget_monthly",
        "balance",
        "Property tax contributes to balance.",
    ),
    CausalEdge(
        "levers.road_maintenance_budget",
        "budget.road_spend",
        "lever_monthly",
        "road_maintenance_budget",
        "budget_monthly",
        "road_spend",
        "Road maintenance lever sets road expenditure.",
    ),
    CausalEdge(
        "levers.water_sewer_capex",
        "budget.water_sewer_spend",
        "lever_monthly",
        "water_sewer_capex",
        "budget_monthly",
        "water_sewer_spend",
        "Water/sewer capex lever sets utility capital spend.",
    ),
)


def edges_from_table(table: str) -> list[CausalEdge]:
    """Return edges that either start or end at the given warehouse table."""
    return [e for e in CAUSAL_EDGES if e.table_source == table or e.table_target == table]


def tax_to_revenue_path() -> list[CausalEdge]:
    """The canonical path judges care about: tax rate → revenue (direct and via population)."""
    return [
        e
        for e in CAUSAL_EDGES
        if (e.column_source == "income_tax_rate" and e.column_target == "income_tax_revenue")
        or (e.column_source == "income" and e.column_target == "income_tax_revenue")
        or (e.column_source == "income_tax_rate" and e.column_target == "disposable_income")
        or (e.column_source == "disposable_income" and e.column_target == "satisfaction")
        or (e.column_source == "satisfaction" and e.column_target == "net")
        or (e.column_source == "net" and e.table_target == "citizen_monthly")
        or (e.column_source == "citizen_id" and e.column_target == "income_tax_revenue")
    ]
