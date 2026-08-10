"""Warehouse table/column catalog used for DataHub emission.

Single source of truth for schema metadata descriptions. The live DDL lives in
`blindcity.sim.warehouse`; this module documents it for the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    native_type: str
    description: str


@dataclass(frozen=True)
class TableSpec:
    name: str
    description: str
    columns: tuple[ColumnSpec, ...]
    # Realistic-but-opaque name used only by the baseline (control) catalog.
    baseline_name: str


# Full catalog: clear names and descriptions. Baseline swaps in baseline_name and strips docs.
TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "sim_run",
        "One simulation invocation: seed, horizon, grid size, wall-clock bounds.",
        (
            ColumnSpec("run_id", "bigint", "Surrogate key for the run."),
            ColumnSpec("seed", "integer", "RNG seed that fully determines the city."),
            ColumnSpec("years", "integer", "Simulated years requested."),
            ColumnSpec("grid_w", "integer", "Map width in tiles."),
            ColumnSpec("grid_h", "integer", "Map height in tiles."),
            ColumnSpec("started_at", "timestamptz", "Wall-clock start."),
            ColumnSpec("finished_at", "timestamptz", "Wall-clock finish, null while running."),
        ),
        baseline_name="t_run",
    ),
    TableSpec(
        "ticks",
        "Simulated calendar: each row is one month of city time for a run.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Months elapsed from start (0 = initial snapshot)."),
            ColumnSpec("year", "integer", "1-based simulated year."),
            ColumnSpec("month", "integer", "1-based month within the year."),
        ),
        baseline_name="t_time",
    ),
    TableSpec(
        "tiles",
        "Spatial grid cells: terrain and zoning. The map the viewer draws.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tile_id", "integer", "Stable tile id (row-major)."),
            ColumnSpec("x", "integer", "Grid column."),
            ColumnSpec("y", "integer", "Grid row."),
            ColumnSpec("terrain", "text", "grass | water | rock."),
            ColumnSpec("zoning", "text", "none | residential | commercial | industrial | mixed."),
        ),
        baseline_name="t_cell",
    ),
    TableSpec(
        "tile_monthly",
        "Per-tile condition each month: abandonment, utility load, power service.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("tile_id", "integer", "Tile."),
            ColumnSpec("condition", "double precision", "0 new … 1 ruined appearance."),
            ColumnSpec("abandonment", "double precision", "0 occupied … 1 abandoned lot."),
            ColumnSpec("power_served", "boolean", "Whether the tile has power this month."),
            ColumnSpec("water_load", "double precision", "Local water load proxy."),
            ColumnSpec("sewer_load", "double precision", "Local sewer load proxy."),
        ),
        baseline_name="t_cell_m",
    ),
    TableSpec(
        "buildings",
        "Structures placed on tiles: type, capacity, assessed value.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("building_id", "integer", "Stable building id."),
            ColumnSpec("tile_id", "integer", "Tile the building occupies."),
            ColumnSpec("building_type", "text", "residential | commercial | industrial | civic."),
            ColumnSpec("capacity", "integer", "Occupancy or job capacity."),
            ColumnSpec("assessed_value", "double precision", "Tax assessment base."),
        ),
        baseline_name="t_bld",
    ),
    TableSpec(
        "building_monthly",
        "Building condition and service each month — what the viewer shades.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("building_id", "integer", "Building."),
            ColumnSpec("condition_band", "text", "new | worn | derelict."),
            ColumnSpec("condition_score", "double precision", "0 new … 1 derelict."),
            ColumnSpec("occupancy", "integer", "Current occupants or workers."),
            ColumnSpec("power_served", "boolean", "Electrified this month."),
            ColumnSpec("power_demand_kw", "double precision", "Electrical demand."),
            ColumnSpec("water_demand", "double precision", "Water demand units."),
        ),
        baseline_name="t_bld_m",
    ),
    TableSpec(
        "households",
        "Households located at a home tile and building.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("household_id", "integer", "Stable household id."),
            ColumnSpec("home_tile_id", "integer", "Home tile."),
            ColumnSpec("home_building_id", "integer", "Home building."),
        ),
        baseline_name="t_hh",
    ),
    TableSpec(
        "citizens",
        "Individual people belonging to households.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("citizen_id", "integer", "Stable citizen id."),
            ColumnSpec("household_id", "integer", "Household membership."),
        ),
        baseline_name="t_person",
    ),
    TableSpec(
        "citizen_monthly",
        "Jobs, income, satisfaction, and map position each month.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("citizen_id", "integer", "Citizen."),
            ColumnSpec("household_id", "integer", "Household."),
            ColumnSpec("home_tile_id", "integer", "Home tile this month."),
            ColumnSpec("workplace_tile_id", "integer", "Workplace tile."),
            ColumnSpec("job_sector", "text", "Employment sector."),
            ColumnSpec("income", "double precision", "Annual gross income."),
            ColumnSpec("disposable_income", "double precision", "Monthly income after tax and bills."),
            ColumnSpec("satisfaction", "double precision", "0–1 well-being score."),
            ColumnSpec("pos_x", "double precision", "Map x position."),
            ColumnSpec("pos_y", "double precision", "Map y position."),
            ColumnSpec("employed", "boolean", "Employment flag."),
            ColumnSpec("uses_transit", "boolean", "Commute mode includes transit."),
        ),
        baseline_name="t_person_m",
    ),
    TableSpec(
        "road_segments",
        "Road network edges on the grid.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("segment_id", "integer", "Stable segment id."),
            ColumnSpec("from_tile_id", "integer", "Start tile."),
            ColumnSpec("to_tile_id", "integer", "End tile."),
            ColumnSpec("from_x", "integer", "Start x."),
            ColumnSpec("from_y", "integer", "Start y."),
            ColumnSpec("to_x", "integer", "End x."),
            ColumnSpec("to_y", "integer", "End y."),
        ),
        baseline_name="t_road",
    ),
    TableSpec(
        "road_monthly",
        "Traffic, wear, and congestion per segment per month.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("segment_id", "integer", "Road segment."),
            ColumnSpec("traffic", "double precision", "Traffic volume."),
            ColumnSpec("wear", "double precision", "0 smooth … 1 ruined pavement."),
            ColumnSpec("congestion", "double precision", "0 free-flow … 1 jammed."),
        ),
        baseline_name="t_road_m",
    ),
    TableSpec(
        "commute_monthly",
        "Home↔work commute outcomes for each citizen each month.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("citizen_id", "integer", "Citizen."),
            ColumnSpec("home_tile_id", "integer", "Home tile."),
            ColumnSpec("workplace_tile_id", "integer", "Workplace tile."),
            ColumnSpec("travel_time", "double precision", "Commute duration units."),
            ColumnSpec("uses_transit", "boolean", "Transit rider flag."),
        ),
        baseline_name="t_commute_m",
    ),
    TableSpec(
        "budget_monthly",
        "Municipal revenue, expenditure, balance, debt, and treasury each month.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("income_tax_revenue", "double precision", "Income tax collected."),
            ColumnSpec("property_tax_revenue", "double precision", "Property tax collected."),
            ColumnSpec("utility_revenue", "double precision", "Electricity bill revenue."),
            ColumnSpec("transit_revenue", "double precision", "Transit fare revenue."),
            ColumnSpec("road_spend", "double precision", "Road maintenance spend."),
            ColumnSpec("water_sewer_spend", "double precision", "Water/sewer capital spend."),
            ColumnSpec("other_spend", "double precision", "Other municipal spend."),
            ColumnSpec("balance", "double precision", "Revenue minus spend."),
            ColumnSpec("debt", "double precision", "Outstanding debt."),
            ColumnSpec("treasury", "double precision", "Cash on hand."),
        ),
        baseline_name="t_budg_m",
    ),
    TableSpec(
        "lever_monthly",
        "Player lever positions in force each month (policy inputs).",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("income_tax_rate", "double precision", "Fraction tax on income."),
            ColumnSpec("property_tax_rate", "double precision", "Annual fraction of assessed value."),
            ColumnSpec("electricity_tariff", "double precision", "Retail currency per kWh."),
            ColumnSpec("road_maintenance_budget", "double precision", "Annual road spend."),
            ColumnSpec("water_sewer_capex", "double precision", "Annual water/sewer capital."),
            ColumnSpec("transit_fare", "double precision", "Fare per ride."),
            ColumnSpec("zoning_release", "double precision", "Share of land opened."),
            ColumnSpec("power_contract_mode", "double precision", "0 spot, 1 fixed, 2 hedged."),
        ),
        baseline_name="t_policy_m",
    ),
    TableSpec(
        "power_monthly",
        "City-wide electricity demand, supply, outages, contract, tariff.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("demand_kw", "double precision", "Aggregate demand."),
            ColumnSpec("supply_kw", "double precision", "Available supply."),
            ColumnSpec("outage_fraction", "double precision", "Share of demand unserved."),
            ColumnSpec("contract_mode", "text", "spot | fixed | hedged."),
            ColumnSpec("tariff", "double precision", "Retail tariff in force."),
        ),
        baseline_name="t_pwr_m",
    ),
    TableSpec(
        "water_monthly",
        "Water and sewer capacity, demand, load ratio, failure rate.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("capacity", "double precision", "System capacity units."),
            ColumnSpec("demand", "double precision", "System demand units."),
            ColumnSpec("load_ratio", "double precision", "demand / capacity."),
            ColumnSpec("failure_rate", "double precision", "Stress-driven failure proxy."),
        ),
        baseline_name="t_h2o_m",
    ),
    TableSpec(
        "migration_monthly",
        "Household arrivals and departures, net migration, population.",
        (
            ColumnSpec("run_id", "bigint", "Owning simulation run."),
            ColumnSpec("tick", "integer", "Simulated month."),
            ColumnSpec("arrivals", "integer", "People arriving."),
            ColumnSpec("departures", "integer", "People leaving."),
            ColumnSpec("net", "integer", "arrivals − departures."),
            ColumnSpec("population", "integer", "Population after migration."),
        ),
        baseline_name="t_mig_m",
    ),
)


GLOSSARY_TERMS: tuple[tuple[str, str, str], ...] = (
    # (name, display_name, definition)
    ("IncomeTaxRate", "Income tax rate", "Municipal fraction levied on household gross income."),
    ("PropertyTaxRate", "Property tax rate", "Annual fraction of building assessed value collected as tax."),
    ("ElectricityTariff", "Electricity tariff", "Retail price charged per kilowatt-hour."),
    ("RoadMaintenanceBudget", "Road maintenance budget", "Annual spend allocated to road repair."),
    ("WaterSewerCapex", "Water and sewer capex", "Annual capital investment in water and sewer capacity."),
    ("TransitFare", "Transit fare", "Price charged per transit ride."),
    ("ZoningRelease", "Zoning release", "Share of undeveloped land opened for development."),
    ("PowerContractMode", "Power contract mode", "Procurement mode: spot, fixed, or hedged."),
    ("CitizenSatisfaction", "Citizen satisfaction", "0–1 well-being of a resident; drives migration."),
    ("DisposableIncome", "Disposable income", "Monthly income remaining after tax and utility/transit bills."),
    ("MunicipalBudget", "Municipal budget", "City revenue, expenditure, balance, debt, and treasury."),
    ("IncomeTaxRevenue", "Income tax revenue", "Tax collected from household incomes in a month."),
    ("RoadWear", "Road wear", "Pavement degradation on a network segment (0–1)."),
    ("Congestion", "Congestion", "Traffic load relative to wear-adjusted capacity (0–1)."),
    ("PowerOutage", "Power outage fraction", "Share of electrical demand left unserved."),
    ("WaterLoadRatio", "Water load ratio", "Water/sewer demand divided by capacity."),
    ("Migration", "Migration", "Households arriving or leaving in response to city conditions."),
    ("BuildingCondition", "Building condition", "Visible state band: new, worn, or derelict."),
    ("Commute", "Commute", "Home-to-work travel along the road network."),
    ("TileZoning", "Tile zoning", "Land-use designation controlling what may be built."),
)


# Which column each glossary term defines, as (term name, table, column).
#
# Without this the terms are emitted as free-floating entities: they exist in DataHub, they are
# searchable in the UI, and nothing links them to the data they describe -- so a dataset query
# returns no terms and the agent's catalog block promised a glossary it could not deliver. Eleven
# of the twenty could be matched by snake-casing the term name, but matching on spelling would
# silently drop the nine that are named for a concept rather than a column, which are the ones
# carrying the causal content ("satisfaction ... drives migration").
TERM_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("IncomeTaxRate", "lever_monthly", "income_tax_rate"),
    ("PropertyTaxRate", "lever_monthly", "property_tax_rate"),
    ("ElectricityTariff", "lever_monthly", "electricity_tariff"),
    ("RoadMaintenanceBudget", "lever_monthly", "road_maintenance_budget"),
    ("WaterSewerCapex", "lever_monthly", "water_sewer_capex"),
    ("TransitFare", "lever_monthly", "transit_fare"),
    ("ZoningRelease", "lever_monthly", "zoning_release"),
    ("PowerContractMode", "lever_monthly", "power_contract_mode"),
    ("CitizenSatisfaction", "citizen_monthly", "satisfaction"),
    ("DisposableIncome", "citizen_monthly", "disposable_income"),
    ("MunicipalBudget", "budget_monthly", "treasury"),
    ("IncomeTaxRevenue", "budget_monthly", "income_tax_revenue"),
    ("RoadWear", "road_monthly", "wear"),
    ("Congestion", "road_monthly", "congestion"),
    ("PowerOutage", "power_monthly", "outage_fraction"),
    ("WaterLoadRatio", "water_monthly", "load_ratio"),
    ("Migration", "migration_monthly", "net"),
    ("BuildingCondition", "building_monthly", "condition_band"),
    ("Commute", "commute_monthly", "travel_time"),
    ("TileZoning", "tiles", "zoning"),
)


# Volume / range assertions emitted into DataHub (full catalog only).
ASSERTIONS: tuple[tuple[str, str, str], ...] = (
    # (table, column_or_*, description)
    ("citizen_monthly", "satisfaction", "Satisfaction is in [0, 1]."),
    ("citizen_monthly", "income", "Income is non-negative."),
    ("budget_monthly", "income_tax_revenue", "Income tax revenue is non-negative."),
    ("road_monthly", "wear", "Road wear is in [0, 1]."),
    ("road_monthly", "congestion", "Congestion is in [0, 1]."),
    ("power_monthly", "outage_fraction", "Outage fraction is in [0, 1]."),
    ("water_monthly", "load_ratio", "Load ratio is non-negative."),
    ("tile_monthly", "*", "Tile monthly history should be large (tiles × months)."),
    ("citizen_monthly", "*", "Citizen monthly history should reach hundreds of thousands of rows."),
)
