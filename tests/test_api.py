"""FastAPI control surface — drives the real app routes, not reimplementations."""

from __future__ import annotations

from fastapi.testclient import TestClient

from blindcity.sim.api import SimSession, create_app, scene_payload


def _client(seed: int = 7) -> TestClient:
    return TestClient(create_app(SimSession(seed=seed)))


def test_get_state_returns_tick_and_levers():
    c = _client()
    r = c.get("/state")
    assert r.status_code == 200
    body = r.json()
    assert "tick" in body
    assert body["tick"] == 0
    assert "levers" in body
    assert "income_tax_rate" in body["levers"]
    assert "lever_meta" in body


def test_post_lever_updates_within_bounds():
    c = _client()
    r = c.post("/lever", json={"name": "income_tax_rate", "value": 0.25})
    assert r.status_code == 200
    assert abs(r.json()["levers"]["income_tax_rate"] - 0.25) < 1e-9
    # Clamp high
    r = c.post("/lever", json={"name": "income_tax_rate", "value": 9.0})
    assert r.status_code == 200
    assert r.json()["levers"]["income_tax_rate"] <= 0.40


def test_post_advance_changes_tick():
    c = _client()
    before = c.get("/state").json()["tick"]
    r = c.post("/advance", json={"months": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["tick_after"] == before + 3
    assert body["tick_before"] == before
    assert c.get("/state").json()["tick"] == before + 3


def test_get_scene_has_spatial_entities_no_health_aggregates():
    c = _client()
    c.post("/advance", json={"months": 1})
    r = c.get("/scene")
    assert r.status_code == 200
    scene = r.json()
    assert scene["grid"]["w"] > 0
    assert len(scene["tiles"]) == scene["grid"]["w"] * scene["grid"]["h"]
    assert scene["buildings"]
    assert scene["roads"]
    assert scene["citizens"]
    # Forbidden dashboard fields — information parity
    forbidden = {
        "population",
        "mean_satisfaction",
        "treasury",
        "health",
        "health_index",
        "debt",
        "balance",
        "revenue",
        "aggregates",
    }
    assert forbidden.isdisjoint(scene.keys())
    # Nested citizen objects should not carry satisfaction/income gauges
    sample = scene["citizens"][0]
    assert "satisfaction" not in sample
    assert "income" not in sample


def test_scene_payload_function_matches_route_contract():
    session = SimSession(seed=3)
    session.advance(2)
    scene = scene_payload(session.state)
    assert "tiles" in scene and "buildings" in scene
    assert "treasury" not in scene


def test_unknown_lever_rejected():
    c = _client()
    r = c.post("/lever", json={"name": "not_a_lever", "value": 1.0})
    assert r.status_code == 400
