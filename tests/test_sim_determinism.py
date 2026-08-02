"""Simulation determinism and spatial structure.

These drive the real shipped engine (`run_simulation` / `create_city`), not a reimplementation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from blindcity.sim.city_init import create_city
from blindcity.sim.engine import run_fingerprint, run_simulation

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_same_seed_same_fingerprint():
    a = run_fingerprint(42, years=2)
    b = run_fingerprint(42, years=2)
    assert a == b


def test_same_seed_identical_across_processes_with_different_pythonhashseed():
    """Guard PYTHONHASHSEED-sensitive iteration (sets / string-keyed dict order).

    In-process identity cannot catch hash randomization. Shell out twice with distinct
    PYTHONHASHSEED values and require byte-identical fingerprints.
    """
    script = (
        "import json;"
        "from blindcity.sim.engine import run_fingerprint;"
        "print(json.dumps(run_fingerprint(42, years=2), sort_keys=True))"
    )
    env_base = os.environ.copy()
    # Ensure the project is importable the same way pytest does (editable install via uv).
    fps = []
    for hashseed in ("0", "1"):
        env = env_base.copy()
        env["PYTHONHASHSEED"] = hashseed
        # Prefer `uv run` so the project venv is used; fall back to sys.executable.
        cmd = ["uv", "run", "python", "-c", script]
        proc = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if proc.returncode != 0:
            # Fallback without uv if the shim is unavailable in the test env.
            cmd = [sys.executable, "-c", script]
            proc = subprocess.run(
                cmd,
                cwd=_REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        assert proc.returncode == 0, (
            f"subprocess failed PYTHONHASHSEED={hashseed}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        line = proc.stdout.strip().splitlines()[-1]
        fps.append(json.loads(line))
    assert fps[0] == fps[1], (
        f"fingerprints diverged across PYTHONHASHSEED values:\n"
        f"  seed=0: {fps[0]}\n  seed=1: {fps[1]}"
    )


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
