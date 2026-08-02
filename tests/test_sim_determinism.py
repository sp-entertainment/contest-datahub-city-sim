"""Simulation determinism and spatial structure.

These drive the real shipped engine (`run_simulation` / `create_city`), not a reimplementation.
"""

from __future__ import annotations

from blindcity.sim.city_init import create_city
from blindcity.sim.engine import run_fingerprint, run_simulation


def test_same_seed_same_fingerprint():
    a = run_fingerprint(42, years=2)
    b = run_fingerprint(42, years=2)
    assert a == b


def test_different_seeds_diverge():
    a = run_fingerprint(1, years=2)
    b = run_fingerprint(2, years=2)
    assert a != b


def test_city_is_spatial():
    city = create_city(42)
    assert city.grid_w > 0 and city.grid_h > 0
    assert len(city.tiles) == city.grid_w * city.grid_h
    assert all(t.terrain for t in city.tiles)
    assert city.buildings, "expected buildings on the map"
    assert city.citizens, "expected located citizens"
    for c in city.citizens:
        assert 0 <= c.home_tile_id < len(city.tiles)
        assert 0 <= c.workplace_tile_id < len(city.tiles)
        home = city.tile_by_id(c.home_tile_id)
        assert c.pos_x >= 0 and c.pos_y >= 0
        assert home.x >= 0


def test_buildings_have_visible_condition_band():
    city = run_simulation(7, years=1)
    bands = {b.condition_band for b in city.buildings}
    assert bands <= {"new", "worn", "derelict"}
    assert bands, "expected at least one building"


def test_budget_has_revenue_and_spend_after_ticks():
    city = run_simulation(42, years=1)
    # After twelve months the economy has run; revenue lines should be non-zero at defaults.
    assert city.budget.income_tax_revenue > 0
    assert city.budget.property_tax_revenue > 0
    assert city.budget.road_spend > 0
    assert city.budget.water_sewer_spend > 0


def test_map_reconstructable_from_state():
    """Tiles + buildings-on-tiles + citizen positions are enough to draw a map."""
    city = run_simulation(42, years=1)
    occupied = {b.tile_id for b in city.buildings}
    assert occupied
    grid = {(t.x, t.y): t for t in city.tiles}
    assert len(grid) == city.grid_w * city.grid_h
    for c in city.citizens[:10]:
        ht = city.tile_by_id(c.home_tile_id)
        assert (ht.x, ht.y) in grid
        assert abs(c.pos_x - ht.x) < 2.0
