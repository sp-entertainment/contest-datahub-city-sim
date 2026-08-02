"""FastAPI control surface for the live simulation.

Endpoints:
  GET  /state   — tick + lever positions (controller-visible; not a dashboard)
  POST /lever   — set one or more levers within bounds
  POST /advance — step one or more months
  GET  /scene   — render-shaped entities for the current tick (no aggregates)

Static files under repo `viewer/` are mounted at `/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from blindcity.levers import LEVERS, defaults
from blindcity.rng import RNG
from blindcity.sim.city_init import create_city
from blindcity.sim.engine import clamp_levers
from blindcity.sim.model import CityState
from blindcity.sim.systems import step_month

# Repo root: src/blindcity/sim/api.py → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_VIEWER_DIR = _REPO_ROOT / "viewer"


class SimSession:
    """Mutable in-process session the control surface drives."""

    def __init__(self, seed: int = 42, levers: dict[str, float] | None = None) -> None:
        self.seed = seed
        self.parent_rng = RNG(seed)
        self.state: CityState = create_city(seed, clamp_levers(levers))

    def set_levers(self, updates: dict[str, float]) -> dict[str, float]:
        merged = dict(self.state.levers)
        for name, value in updates.items():
            if name not in LEVERS:
                raise KeyError(name)
            merged[name] = LEVERS[name].clamp(float(value))
        self.state.levers = merged
        return dict(self.state.levers)

    def advance(self, months: int = 1) -> CityState:
        if months < 1:
            raise ValueError("months must be >= 1")
        for _ in range(months):
            step_month(self.state, self.parent_rng.stream("tick"))
        return self.state

    def reset(self, seed: int | None = None, levers: dict[str, float] | None = None) -> None:
        if seed is not None:
            self.seed = seed
        self.parent_rng = RNG(self.seed)
        self.state = create_city(self.seed, clamp_levers(levers or defaults()))


def state_payload(session: SimSession) -> dict[str, Any]:
    """Controller-visible state: tick, calendar, levers. No health aggregates."""
    st = session.state
    year, month = st.year_month()
    return {
        "seed": session.seed,
        "tick": st.tick,
        "year": year,
        "month": month,
        "levers": dict(st.levers),
        "lever_meta": {
            name: {
                "minimum": lev.minimum,
                "maximum": lev.maximum,
                "default": lev.default,
                "unit": lev.unit,
                "description": lev.description,
            }
            for name, lev in LEVERS.items()
        },
    }


def scene_payload(state: CityState) -> dict[str, Any]:
    """Everything the viewer draws — spatial entities only, no derived city-health stats.

    Deliberately omits: population totals, mean satisfaction, treasury, balances, indices.
    Condition bands and booleans are visual properties of entities, not dashboard numbers.
    """
    return {
        "tick": state.tick,
        "grid": {"w": state.grid_w, "h": state.grid_h},
        "tiles": [
            {
                "id": t.tile_id,
                "x": t.x,
                "y": t.y,
                "terrain": t.terrain,
                "zoning": t.zoning,
                # Visual only — shade of lot, not a gauge
                "condition": t.condition,
                "abandonment": t.abandonment,
                "power_served": t.power_served,
            }
            for t in state.tiles
        ],
        "buildings": [
            {
                "id": b.building_id,
                "tile_id": b.tile_id,
                "building_type": b.building_type,
                "condition_band": b.condition_band,
                "power_served": b.power_served,
            }
            for b in state.buildings
        ],
        "roads": [
            {
                "id": r.segment_id,
                "from_tile_id": r.from_tile_id,
                "to_tile_id": r.to_tile_id,
                "from_x": r.from_x,
                "from_y": r.from_y,
                "to_x": r.to_x,
                "to_y": r.to_y,
                # Visual wear / traffic for rendering road appearance
                "wear": r.wear,
                "congestion": r.congestion,
            }
            for r in state.roads
        ],
        "citizens": [
            {
                "id": c.citizen_id,
                "x": c.pos_x,
                "y": c.pos_y,
                "home_tile_id": c.home_tile_id,
                "workplace_tile_id": c.workplace_tile_id,
            }
            for c in state.citizens
        ],
        # Utility coverage as per-entity flags already on buildings/tiles; no city-wide rates.
    }


class LeverBody(BaseModel):
    """Set one lever by name, or several via `levers` map."""

    name: str | None = None
    value: float | None = None
    levers: dict[str, float] | None = None


class AdvanceBody(BaseModel):
    months: int = Field(default=1, ge=1, le=120)


class ResetBody(BaseModel):
    seed: int = 42
    levers: dict[str, float] | None = None


def create_app(session: SimSession | None = None) -> FastAPI:
    """Build the app. Tests inject a session; serve creates a default one."""
    app = FastAPI(title="Blind City control surface", version="0.1.0")
    app.state.session = session or SimSession(seed=42)

    @app.get("/state")
    def get_state() -> dict[str, Any]:
        return state_payload(app.state.session)

    @app.post("/lever")
    def post_lever(body: LeverBody) -> dict[str, Any]:
        updates: dict[str, float] = {}
        if body.levers:
            updates.update(body.levers)
        if body.name is not None:
            if body.value is None:
                raise HTTPException(status_code=400, detail="value required when name is set")
            updates[body.name] = body.value
        if not updates:
            raise HTTPException(status_code=400, detail="provide name+value or levers map")
        try:
            levers = app.state.session.set_levers(updates)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"unknown lever: {exc.args[0]}") from exc
        return {"levers": levers, "tick": app.state.session.state.tick}

    @app.post("/advance")
    def post_advance(body: AdvanceBody | None = None) -> dict[str, Any]:
        months = 1 if body is None else body.months
        before = app.state.session.state.tick
        app.state.session.advance(months)
        after = app.state.session.state.tick
        return {
            "tick_before": before,
            "tick_after": after,
            "months": months,
            "state": state_payload(app.state.session),
        }

    @app.get("/scene")
    def get_scene() -> dict[str, Any]:
        return scene_payload(app.state.session.state)

    @app.post("/reset")
    def post_reset(body: ResetBody | None = None) -> dict[str, Any]:
        seed = 42 if body is None else body.seed
        levers = None if body is None else body.levers
        app.state.session.reset(seed=seed, levers=levers)
        return state_payload(app.state.session)

    if _VIEWER_DIR.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_VIEWER_DIR), html=True),
            name="viewer",
        )

    return app


# Module-level app for `uvicorn blindcity.sim.api:app`
app = create_app()
