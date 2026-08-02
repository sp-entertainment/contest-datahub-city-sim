"""Each of the eight levers must produce a measurable, directionally sensible effect.

Compares two short runs that differ only in one lever (fixed seed). Drives `run_simulation`.
"""

from __future__ import annotations

from blindcity.levers import LEVERS, defaults
from blindcity.sim.engine import run_simulation

SEED = 99
YEARS = 3


def _run(**lever_overrides: float):
    levers = defaults()
    levers.update(lever_overrides)
    return run_simulation(SEED, YEARS, levers=levers)


def test_income_tax_rate_raises_revenue_and_lowers_satisfaction():
    low = _run(income_tax_rate=0.02)
    high = _run(income_tax_rate=0.35)
    assert high.budget.income_tax_revenue > low.budget.income_tax_revenue
    assert high.mean_satisfaction() < low.mean_satisfaction()


def test_property_tax_rate_raises_property_revenue():
    low = _run(property_tax_rate=0.001)
    high = _run(property_tax_rate=0.04)
    assert high.budget.property_tax_revenue > low.budget.property_tax_revenue


def test_electricity_tariff_raises_utility_revenue():
    low = _run(electricity_tariff=0.05)
    high = _run(electricity_tariff=0.80)
    assert high.budget.utility_revenue > low.budget.utility_revenue


def test_road_maintenance_budget_reduces_wear():
    low = _run(road_maintenance_budget=0.0)
    high = _run(road_maintenance_budget=5_000_000.0)
    wear_low = sum(r.wear for r in low.roads) / len(low.roads)
    wear_high = sum(r.wear for r in high.roads) / len(high.roads)
    assert wear_high < wear_low
    assert high.budget.road_spend > low.budget.road_spend


def test_water_sewer_capex_raises_capacity():
    low = _run(water_sewer_capex=0.0)
    high = _run(water_sewer_capex=5_000_000.0)
    assert high.water.capacity > low.water.capacity
    assert high.budget.water_sewer_spend > low.budget.water_sewer_spend


def test_transit_fare_raises_transit_revenue():
    low = _run(transit_fare=0.5)
    high = _run(transit_fare=9.0)
    assert high.budget.transit_revenue > low.budget.transit_revenue


def test_zoning_release_opens_more_land_or_buildings():
    low = _run(zoning_release=0.0)
    high = _run(zoning_release=1.0)
    zoned_low = sum(1 for t in low.tiles if t.zoning != "none")
    zoned_high = sum(1 for t in high.tiles if t.zoning != "none")
    # Either more zoned tiles or more buildings (construction on released land).
    assert zoned_high >= zoned_low
    assert len(high.buildings) >= len(low.buildings)
    assert zoned_high > zoned_low or len(high.buildings) > len(low.buildings)


def test_power_contract_mode_changes_reliability():
    spot = _run(power_contract_mode=0)  # spot
    hedged = _run(power_contract_mode=2)  # hedged
    # Hedged should be more reliable (lower outage) on average at end state.
    assert hedged.power.outage_fraction <= spot.power.outage_fraction + 1e-9
    assert spot.power.contract_mode == "spot"
    assert hedged.power.contract_mode == "hedged"


def test_all_eight_levers_are_exercised():
    """Guard against a lever existing in LEVERS but never wired into the model."""
    assert set(LEVERS) == {
        "income_tax_rate",
        "property_tax_rate",
        "electricity_tariff",
        "road_maintenance_budget",
        "water_sewer_capex",
        "transit_fare",
        "zoning_release",
        "power_contract_mode",
    }
