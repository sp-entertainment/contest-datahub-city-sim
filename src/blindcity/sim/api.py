"""FastAPI control surface for the live simulation.

Endpoints:
  GET  /state   — tick + lever positions (controller-visible; not a dashboard)
  POST /lever   — set one or more levers within bounds
  POST /advance — step one or more months
  GET  /scene   — render-shaped entities for the current tick (no aggregates)

Static files under repo `viewer/` are mounted at `/`.
"""

from __future__ import annotations

import time
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
    """Mutable in-process session the control surface drives.

    Free play: a healthy city at tick 0, advanced as many times as you like. `HumanRunSession`
    below is the scored counterpart. `create_app` reads the two attributes underneath through
    `getattr`, so the session types stay duck-typed rather than sharing a base class.
    """

    # No turn budget and no briefing: free play is not a scored run.
    progress: dict[str, Any] | None = None
    briefing: dict[str, Any] | None = None

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


class RunNotAcceptingTurns(RuntimeError):
    """A turn was submitted after the budget was spent."""


class HumanRunSession:
    """A scored run driven from the browser. The harness owns the city; this only forwards.

    Duck-typed to what `create_app` uses -- `seed`, `state`, `set_levers`, `advance` -- so every
    endpoint is shared with free play and nothing about the app branches on which one it has.

    `state` is a reference to the very object `RunHarness.run` is stepping. The harness mutates it
    in place, so one reference stays correct for the whole run and there is no copy to keep in sync.
    """

    def __init__(
        self,
        controller: Any,
        state: CityState,
        *,
        seed: int,
        turn_budget: int = 12,
        months_per_turn: int = 3,
        briefing: dict[str, Any] | None = None,
        advance_timeout: float = 120.0,
    ) -> None:
        self.controller = controller
        self.state = state
        self.seed = seed
        self.turn_budget = turn_budget
        self.months_per_turn = months_per_turn
        self.briefing = briefing
        self.advance_timeout = advance_timeout
        # The tick the controller took over on, so turns played can be counted from the clock.
        self.start_tick = state.tick

    @property
    def turns_played(self) -> int:
        """Counted from the simulation clock rather than signalled across threads.

        The harness steps one month at a time and only updates its own turn counter when it comes
        back round to `decide()`, so anything read from the controller mid-turn is a turn behind.
        The tick cannot be: it is the thing the turn is made of.
        """
        return (self.state.tick - self.start_tick) // self.months_per_turn

    @property
    def progress(self) -> dict[str, Any]:
        played = self.turns_played
        return {
            "turn": min(played, self.turn_budget - 1),
            "turns_played": played,
            "turn_budget": self.turn_budget,
            # Read from the clock as well as the controller's flag. The flag is set on the harness
            # thread once `run()` returns, which is a moment after the final month lands -- so the
            # response to the last `/advance` would carry `complete: false` and the browser would
            # sit on "Quarter complete" until something else polled.
            "complete": played >= self.turn_budget or bool(self.controller.progress.get("complete")),
        }

    def set_levers(self, updates: dict[str, float]) -> dict[str, float]:
        """Stage lever positions. Nothing reaches the simulation until the turn is submitted."""
        merged = dict(self.state.levers)
        for name, value in updates.items():
            if name not in LEVERS:
                raise KeyError(name)
            merged[name] = LEVERS[name].clamp(float(value))
        self.state.levers = merged
        return dict(self.state.levers)

    def advance(self, months: int = 1) -> CityState:
        """Submit the staged levers as one turn and wait for the harness to play it.

        `months` is ignored: the scenario's `months_per_turn` decides how far a turn moves, the
        same as it does for every agent.

        Waits for the *whole* turn, not merely for movement. The harness steps a month at a time,
        so returning on the first tick change hands the browser a city one month into a three month
        quarter -- and the canvas then draws a turn that is still being played. Waiting on the clock
        rather than on a completion signal also means the final turn needs no special case.
        """
        if self.progress["complete"]:
            raise RunNotAcceptingTurns("the run is over; every turn in the budget has been played")
        target = self.state.tick + self.months_per_turn
        self.controller.submit(dict(self.state.levers))
        deadline = time.monotonic() + self.advance_timeout
        while self.state.tick < target and time.monotonic() < deadline:
            time.sleep(0.02)
        if self.state.tick < target:
            raise TimeoutError("the run did not finish the turn; is the harness still playing?")
        return self.state

    def reset(self, seed: int | None = None, levers: dict[str, float] | None = None) -> None:
        raise RunNotAcceptingTurns("a scored run cannot be reset; restart `blindcity run`")


def state_payload(session: SimSession | HumanRunSession) -> dict[str, Any]:
    """Controller-visible state: tick, calendar, levers. No health aggregates.

    Two optional blocks are attached for a scored human run and are absent for free play:
    `progress`, which is the turn number and budget every agent is also told, and `briefing`,
    which is the one deliberate exception to the no-numbers rule -- a fixed starting snapshot
    shown once in the help panel. Neither is a live readout of the city.
    """
    st = session.state
    year, month = st.year_month()
    payload: dict[str, Any] = {
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
    progress = getattr(session, "progress", None)
    if progress is not None:
        payload["progress"] = dict(progress)
    briefing = getattr(session, "briefing", None)
    if briefing is not None:
        payload["briefing"] = dict(briefing)
    return payload


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
    app = FastAPI(title="City Sim control surface", version="0.1.0")
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
        try:
            app.state.session.advance(months)
        except RunNotAcceptingTurns as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        after = app.state.session.state.tick
        return {
            "tick_before": before,
            "tick_after": after,
            "months": after - before,
            "state": state_payload(app.state.session),
        }

    @app.get("/scene")
    def get_scene() -> dict[str, Any]:
        return scene_payload(app.state.session.state)

    @app.post("/reset")
    def post_reset(body: ResetBody | None = None) -> dict[str, Any]:
        seed = 42 if body is None else body.seed
        levers = None if body is None else body.levers
        try:
            app.state.session.reset(seed=seed, levers=levers)
        except RunNotAcceptingTurns as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
