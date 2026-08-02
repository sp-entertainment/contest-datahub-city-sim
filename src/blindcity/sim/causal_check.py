"""Empirical validation of the causal graph.

`causal.py` declares the edges. This module proves each one is real by experiment: perturb the
source, run the code that computes the target, and require the target to move in the stated
direction. An edge nobody can demonstrate fails the build.

Why this exists: the edge list is what DataHub lineage is generated from, and a hand-maintained
edge list can drift from the equations silently — which is exactly the failure this project set out
to beat. Validation closes that gap. The claim we can defend is not "the lineage was derived from
the code" but "every lineage edge is verified against the running simulation", which is stronger
than what most real data platforms can say about their own lineage.

Two kinds of check:

- **lever** — run two full simulations differing in one lever, compare an observable. Same shape as
  `tests/test_lever_effects.py`.
- **injected** — build a city, set the source field directly, call the system function that consumes
  it, and compare the target against an unperturbed control. `systems.py` exposes
  `assign_power_service`, `compute_water_load`, `compute_congestion`, and `compute_balance` for
  exactly this reason.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

from blindcity.levers import defaults
from blindcity.rng import RNG
from blindcity.sim import systems
from blindcity.sim.causal import CAUSAL_EDGES, CausalEdge
from blindcity.sim.engine import run_simulation
from blindcity.sim.model import CityState

SEED = 99
YEARS = 2
_CHECK_RNG_SEED = 4242

_sim_cache: dict[tuple[str, float], CityState] = {}
_city_cache: dict[int, CityState] = {}


def _sim(lever: str, value: float) -> CityState:
    """A full run with one lever overridden. Cached — the same run is reused across edges."""
    key = (lever, value)
    if key not in _sim_cache:
        levers = defaults()
        levers[lever] = value
        _sim_cache[key] = run_simulation(SEED, YEARS, levers=levers)
    return _sim_cache[key]


def _city(years: int = 1) -> CityState:
    """A settled city to perturb. Cached; always deep-copied before mutation."""
    if years not in _city_cache:
        _city_cache[years] = run_simulation(SEED, years)
    return copy.deepcopy(_city_cache[years])


def _rng(name: str) -> RNG:
    """A fixed RNG so injected checks are reproducible and independent of sim state."""
    return RNG(_CHECK_RNG_SEED).stream(name)


Result = tuple[bool, str]


def _cmp(label: str, low: float, high: float) -> Result:
    """Require high > low, and report the numbers either way."""
    ok = high > low
    return ok, f"{label}: low={low:.6g} high={high:.6g}"


def _cmp_lt(label: str, low: float, high: float) -> Result:
    """Require high < low."""
    ok = high < low
    return ok, f"{label}: low={low:.6g} high={high:.6g}"


# --------------------------------------------------------------------------------------
# Lever edges — two full runs, one lever apart.
# --------------------------------------------------------------------------------------


def _mean_wear(state: CityState) -> float:
    return sum(r.wear for r in state.roads) / len(state.roads) if state.roads else 0.0


def check_income_tax_to_revenue() -> Result:
    return _cmp(
        "income_tax_revenue",
        _sim("income_tax_rate", 0.02).budget.income_tax_revenue,
        _sim("income_tax_rate", 0.35).budget.income_tax_revenue,
    )


def check_income_tax_to_disposable() -> Result:
    def mean_di(s: CityState) -> float:
        return sum(c.disposable_income for c in s.citizens) / max(1, len(s.citizens))

    return _cmp_lt(
        "disposable_income",
        mean_di(_sim("income_tax_rate", 0.02)),
        mean_di(_sim("income_tax_rate", 0.35)),
    )


def check_property_tax_to_revenue() -> Result:
    return _cmp(
        "property_tax_revenue",
        _sim("property_tax_rate", 0.001).budget.property_tax_revenue,
        _sim("property_tax_rate", 0.04).budget.property_tax_revenue,
    )


def check_property_tax_to_satisfaction() -> Result:
    return _cmp_lt(
        "mean_satisfaction",
        _sim("property_tax_rate", 0.001).mean_satisfaction(),
        _sim("property_tax_rate", 0.04).mean_satisfaction(),
    )


def check_tariff_to_utility_revenue() -> Result:
    return _cmp(
        "utility_revenue",
        _sim("electricity_tariff", 0.05).budget.utility_revenue,
        _sim("electricity_tariff", 0.80).budget.utility_revenue,
    )


def check_tariff_to_satisfaction() -> Result:
    return _cmp_lt(
        "mean_satisfaction",
        _sim("electricity_tariff", 0.05).mean_satisfaction(),
        _sim("electricity_tariff", 0.80).mean_satisfaction(),
    )


def check_contract_mode_to_outage() -> Result:
    spot = _sim("power_contract_mode", 0).power.outage_fraction
    hedged = _sim("power_contract_mode", 2).power.outage_fraction
    return hedged <= spot, f"outage_fraction: spot={spot:.6g} hedged={hedged:.6g}"


def check_maintenance_to_wear() -> Result:
    return _cmp_lt(
        "mean_road_wear",
        _mean_wear(_sim("road_maintenance_budget", 0.0)),
        _mean_wear(_sim("road_maintenance_budget", 5_000_000.0)),
    )


def check_maintenance_to_road_spend() -> Result:
    return _cmp(
        "road_spend",
        _sim("road_maintenance_budget", 0.0).budget.road_spend,
        _sim("road_maintenance_budget", 5_000_000.0).budget.road_spend,
    )


def check_capex_to_capacity() -> Result:
    return _cmp(
        "water_capacity",
        _sim("water_sewer_capex", 0.0).water.capacity,
        _sim("water_sewer_capex", 5_000_000.0).water.capacity,
    )


def check_capex_to_water_spend() -> Result:
    return _cmp(
        "water_sewer_spend",
        _sim("water_sewer_capex", 0.0).budget.water_sewer_spend,
        _sim("water_sewer_capex", 5_000_000.0).budget.water_sewer_spend,
    )


def check_fare_to_transit_revenue() -> Result:
    return _cmp(
        "transit_revenue",
        _sim("transit_fare", 0.5).budget.transit_revenue,
        _sim("transit_fare", 9.0).budget.transit_revenue,
    )


def check_fare_to_satisfaction() -> Result:
    return _cmp_lt(
        "mean_satisfaction",
        _sim("transit_fare", 0.5).mean_satisfaction(),
        _sim("transit_fare", 9.0).mean_satisfaction(),
    )


def check_zoning_release_to_zoning() -> Result:
    def zoned(s: CityState) -> float:
        return float(sum(1 for t in s.tiles if t.zoning != "none"))

    return _cmp("zoned_tiles", zoned(_sim("zoning_release", 0.0)), zoned(_sim("zoning_release", 1.0)))


# --------------------------------------------------------------------------------------
# Injected edges — set the source, run the consuming function, compare against a control.
# --------------------------------------------------------------------------------------


def check_disposable_to_satisfaction() -> Result:
    poor, rich = _city(), _city()
    for c in poor.citizens:
        c.disposable_income = 0.0
    for c in rich.citizens:
        c.disposable_income = 8_000.0
    systems.apply_satisfaction(poor, _rng("sat.poor"))
    systems.apply_satisfaction(rich, _rng("sat.rich"))
    return _cmp("mean_satisfaction", poor.mean_satisfaction(), rich.mean_satisfaction())


def check_outage_to_power_served() -> Result:
    clear, dark = _city(), _city()
    clear.power.outage_fraction = 0.0
    dark.power.outage_fraction = 1.0
    systems.assign_power_service(clear, _rng("pwr.clear"))
    systems.assign_power_service(dark, _rng("pwr.dark"))
    served_clear = sum(1 for b in clear.buildings if b.power_served)
    served_dark = sum(1 for b in dark.buildings if b.power_served)
    return served_dark < served_clear, f"buildings served: clear={served_clear} dark={served_dark}"


def check_power_served_to_satisfaction() -> Result:
    lit, dark = _city(), _city()
    for b in lit.buildings:
        b.power_served = True
    for b in dark.buildings:
        b.power_served = False
    systems.apply_satisfaction(lit, _rng("sat.lit"))
    systems.apply_satisfaction(dark, _rng("sat.dark"))
    return _cmp("mean_satisfaction", dark.mean_satisfaction(), lit.mean_satisfaction())


def check_wear_to_congestion() -> Result:
    smooth, broken = _city(), _city()
    for r in smooth.roads:
        r.wear = 0.0
    for r in broken.roads:
        r.wear = 1.0
    systems.compute_congestion(smooth)
    systems.compute_congestion(broken)

    def mean_c(s: CityState) -> float:
        return sum(r.congestion for r in s.roads) / max(1, len(s.roads))

    return _cmp("mean_congestion", mean_c(smooth), mean_c(broken))


def check_congestion_to_travel_time() -> Result:
    free, jammed = _city(), _city()
    for r in free.roads:
        r.congestion = 0.0
    for r in jammed.roads:
        r.congestion = 1.0
    systems.apply_commute(free, _rng("commute.free"))
    systems.apply_commute(jammed, _rng("commute.jam"))

    def mean_tt(s: CityState) -> float:
        return sum(c.commute_travel_time for c in s.citizens) / max(1, len(s.citizens))

    return _cmp("mean_travel_time", mean_tt(free), mean_tt(jammed))


def check_travel_time_to_satisfaction() -> Result:
    short, long = _city(), _city()
    for c in short.citizens:
        c.commute_travel_time = 0.0
    for c in long.citizens:
        c.commute_travel_time = 40.0
    systems.apply_satisfaction(short, _rng("sat.short"))
    systems.apply_satisfaction(long, _rng("sat.long"))
    return _cmp("mean_satisfaction", long.mean_satisfaction(), short.mean_satisfaction())


def check_capacity_to_load_ratio() -> Result:
    tight, ample = _city(), _city()
    tight.water.capacity = 100.0
    ample.water.capacity = 100_000.0
    systems.compute_water_load(tight)
    systems.compute_water_load(ample)
    return _cmp("water_load_ratio", ample.water.load_ratio, tight.water.load_ratio)


def check_load_ratio_to_satisfaction() -> Result:
    ok_city, strained = _city(), _city()
    ok_city.water.load_ratio = 0.0
    strained.water.load_ratio = 3.0
    systems.apply_satisfaction(ok_city, _rng("sat.water.ok"))
    systems.apply_satisfaction(strained, _rng("sat.water.bad"))
    return _cmp("mean_satisfaction", strained.mean_satisfaction(), ok_city.mean_satisfaction())


def check_zoning_to_buildings() -> Result:
    """Zoned empty land must be a precondition for construction.

    The control has *every* empty tile un-zoned, so it has nowhere legal to build; the treatment
    zones some of that same land. Both arms get the identical RNG stream, so any difference is the
    zoning and nothing else. Construction is probabilistic, so several trials are run: the control
    must never build, and the treatment must build at least once.
    """
    built_in_treatment = 0
    trials = 10
    for i in range(trials):
        control, treatment = _city(), _city()
        for state in (control, treatment):
            state.levers["zoning_release"] = 0.0
            occupied = {b.tile_id for b in state.buildings}
            # Strip zoning from all empty land, so neither arm has leftover buildable tiles.
            for t in state.tiles:
                if t.tile_id not in occupied:
                    t.zoning = "none"

        occupied_t = {b.tile_id for b in treatment.buildings}
        opened = 0
        for t in treatment.tiles:
            if t.terrain == "grass" and t.tile_id not in occupied_t:
                t.zoning = "residential"
                opened += 1
                if opened >= 30:
                    break
        if opened == 0:
            return False, "no empty grass tiles available to zone"

        before_c, before_t = len(control.buildings), len(treatment.buildings)
        # Identical stream for both arms — the only difference is the zoning.
        systems.apply_zoning_growth(control, _rng(f"zone.{i}"))
        systems.apply_zoning_growth(treatment, _rng(f"zone.{i}"))
        built_c = len(control.buildings) - before_c
        built_t = len(treatment.buildings) - before_t
        if built_c > 0:
            return False, f"trial {i}: built {built_c} buildings with no land zoned"
        if built_t > 0:
            built_in_treatment += 1
    ok = built_in_treatment > 0
    return ok, f"unzoned land never built; zoned land built in {built_in_treatment}/{trials} trials"


def check_satisfaction_to_migration() -> Result:
    happy, unhappy = _city(), _city()
    for c in happy.citizens:
        c.satisfaction = 0.95
    for c in unhappy.citizens:
        c.satisfaction = 0.05
    systems.apply_migration(happy, _rng("mig.happy"))
    systems.apply_migration(unhappy, _rng("mig.unhappy"))
    return _cmp("migration_net", float(unhappy.migration.net), float(happy.migration.net))


def check_migration_to_population() -> Result:
    """Net migration must equal the change in population — a structural identity, not a trend."""
    for label, sat in (("happy", 0.95), ("unhappy", 0.05)):
        city = _city()
        for c in city.citizens:
            c.satisfaction = sat
        before = city.population()
        systems.apply_migration(city, _rng(f"mig.pop.{label}"))
        delta = city.population() - before
        if delta != city.migration.net:
            return False, f"{label}: population delta {delta} != migration net {city.migration.net}"
        if city.migration.net == 0:
            return False, f"{label}: no migration occurred, edge not exercised"
    return True, "population delta equals migration net in both directions"


def check_population_to_revenue() -> Result:
    full, halved = _city(), _city()
    halved.citizens = [c for i, c in enumerate(halved.citizens) if i % 2 == 0]
    systems.apply_economy(full, _rng("econ.full"))
    systems.apply_economy(halved, _rng("econ.half"))
    return _cmp(
        "income_tax_revenue",
        halved.budget.income_tax_revenue,
        full.budget.income_tax_revenue,
    )


def check_income_to_revenue() -> Result:
    base, rich = _city(), _city()
    for c in rich.citizens:
        c.income *= 2.0
    systems.apply_economy(base, _rng("econ.base"))
    systems.apply_economy(rich, _rng("econ.rich"))
    return _cmp(
        "income_tax_revenue",
        base.budget.income_tax_revenue,
        rich.budget.income_tax_revenue,
    )


def _balance_from_revenue(field: str) -> Result:
    low, high = _city(), _city()
    for state, value in ((low, 0.0), (high, 1_000_000.0)):
        setattr(state.budget, field, value)
        systems.compute_balance(state)
    return _cmp(f"balance via {field}", low.budget.balance, high.budget.balance)


def check_income_revenue_to_balance() -> Result:
    return _balance_from_revenue("income_tax_revenue")


def check_property_revenue_to_balance() -> Result:
    return _balance_from_revenue("property_tax_revenue")


# --------------------------------------------------------------------------------------
# Edge → check registry. Every edge in CAUSAL_EDGES must appear here.
# --------------------------------------------------------------------------------------

CHECKS: dict[tuple[str, str], Callable[[], Result]] = {
    ("levers.income_tax_rate", "budget.income_tax_revenue"): check_income_tax_to_revenue,
    ("levers.income_tax_rate", "citizens.disposable_income"): check_income_tax_to_disposable,
    ("citizens.disposable_income", "citizens.satisfaction"): check_disposable_to_satisfaction,
    ("levers.property_tax_rate", "budget.property_tax_revenue"): check_property_tax_to_revenue,
    ("levers.property_tax_rate", "citizens.satisfaction"): check_property_tax_to_satisfaction,
    ("levers.electricity_tariff", "budget.utility_revenue"): check_tariff_to_utility_revenue,
    ("levers.electricity_tariff", "citizens.satisfaction"): check_tariff_to_satisfaction,
    ("levers.power_contract_mode", "power.outage_fraction"): check_contract_mode_to_outage,
    ("power.outage_fraction", "buildings.power_served"): check_outage_to_power_served,
    ("buildings.power_served", "citizens.satisfaction"): check_power_served_to_satisfaction,
    ("levers.road_maintenance_budget", "roads.wear"): check_maintenance_to_wear,
    ("roads.wear", "roads.congestion"): check_wear_to_congestion,
    ("roads.congestion", "commute.travel_time"): check_congestion_to_travel_time,
    ("commute.travel_time", "citizens.satisfaction"): check_travel_time_to_satisfaction,
    ("levers.water_sewer_capex", "water.capacity"): check_capex_to_capacity,
    ("water.capacity", "water.load_ratio"): check_capacity_to_load_ratio,
    ("water.load_ratio", "citizens.satisfaction"): check_load_ratio_to_satisfaction,
    ("levers.transit_fare", "budget.transit_revenue"): check_fare_to_transit_revenue,
    ("levers.transit_fare", "citizens.satisfaction"): check_fare_to_satisfaction,
    ("levers.zoning_release", "tiles.zoning"): check_zoning_release_to_zoning,
    ("tiles.zoning", "buildings.count"): check_zoning_to_buildings,
    ("citizens.satisfaction", "migration.net"): check_satisfaction_to_migration,
    ("migration.net", "citizens.population"): check_migration_to_population,
    ("citizens.population", "budget.income_tax_revenue"): check_population_to_revenue,
    ("citizens.income", "budget.income_tax_revenue"): check_income_to_revenue,
    ("budget.income_tax_revenue", "budget.balance"): check_income_revenue_to_balance,
    ("budget.property_tax_revenue", "budget.balance"): check_property_revenue_to_balance,
    ("levers.road_maintenance_budget", "budget.road_spend"): check_maintenance_to_road_spend,
    ("levers.water_sewer_capex", "budget.water_sewer_spend"): check_capex_to_water_spend,
}


@dataclass(frozen=True)
class EdgeVerdict:
    edge: CausalEdge
    ok: bool
    detail: str


def unchecked_edges() -> list[CausalEdge]:
    """Declared edges with no experiment behind them. Must always be empty."""
    return [e for e in CAUSAL_EDGES if (e.source, e.target) not in CHECKS]


def orphan_checks() -> list[tuple[str, str]]:
    """Checks for edges that no longer exist. Must always be empty."""
    declared = {(e.source, e.target) for e in CAUSAL_EDGES}
    return [key for key in CHECKS if key not in declared]


def validate_edges() -> list[EdgeVerdict]:
    """Run every edge's experiment. This is what makes the lineage a claim rather than an assertion."""
    verdicts: list[EdgeVerdict] = []
    for edge in CAUSAL_EDGES:
        check = CHECKS.get((edge.source, edge.target))
        if check is None:
            verdicts.append(EdgeVerdict(edge, False, "no check registered for this edge"))
            continue
        ok, detail = check()
        verdicts.append(EdgeVerdict(edge, ok, detail))
    return verdicts
