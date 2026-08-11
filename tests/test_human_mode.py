"""The `human` mode: a person in a browser, scored by the same harness as every agent.

Driven programmatically here. A background thread stands in for the player, so the whole loop is
exercised with no browser and no warehouse.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from blindcity.benchmark.harness import RunHarness
from blindcity.benchmark.human import HumanController
from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS, Scenario
from blindcity.sim.api import HumanRunSession, SimSession, create_app

# Three turns rather than twelve. The loop is identical and the test stays quick.
SHORT = Scenario(
    name=INFRASTRUCTURE_CRISIS.name,
    seed=INFRASTRUCTURE_CRISIS.seed,
    # Two months of "crisis" instead of sixty: this exercises the wiring, not the calibration.
    crisis_months=2,
    turn_budget=3,
    months_per_turn=INFRASTRUCTURE_CRISIS.months_per_turn,
    crisis_levers=INFRASTRUCTURE_CRISIS.crisis_levers,
)


def _session(controller, prepared, **kw) -> HumanRunSession:
    return HumanRunSession(
        controller,
        prepared.state,
        seed=SHORT.seed,
        turn_budget=SHORT.turn_budget,
        months_per_turn=SHORT.months_per_turn,
        **kw,
    )


def _play(client: TestClient, turns: int, levers: dict[str, float] | None = None) -> None:
    """Stand in for the player: set levers, submit the turn, repeat."""
    for _ in range(turns):
        if levers:
            client.post("/lever", json={"levers": levers})
        client.post("/advance", json={"months": 3})


def test_a_human_run_is_scored_by_the_same_harness_as_every_agent():
    harness = RunHarness(SHORT)
    prepared = harness.prepare()
    controller = HumanController(turn_budget=SHORT.turn_budget)
    session = _session(controller, prepared)
    client = TestClient(create_app(session))

    player = threading.Thread(
        target=_play, args=(client, SHORT.turn_budget, {"income_tax_rate": 0.11}), daemon=True
    )
    player.start()
    result = harness.run(controller, mode="human", prepared=prepared)
    controller.finish()
    player.join(timeout=30)

    assert len(result.turns) == SHORT.turn_budget
    assert result.mode == "human"
    assert 0.0 <= result.final_index <= 1.0
    # What the browser sent reached the simulation, clamped through the same path as an agent's.
    assert result.turns[-1].levers["income_tax_rate"] == pytest.approx(0.11)


def test_the_run_refuses_turns_once_the_budget_is_spent():
    harness = RunHarness(SHORT)
    prepared = harness.prepare()
    controller = HumanController(turn_budget=SHORT.turn_budget)
    session = _session(controller, prepared)
    client = TestClient(create_app(session))

    player = threading.Thread(target=_play, args=(client, SHORT.turn_budget), daemon=True)
    player.start()
    harness.run(controller, mode="human", prepared=prepared)
    controller.finish()
    player.join(timeout=30)

    # A thirteenth quarter is not a turn played badly, it is a turn that does not exist.
    assert client.post("/advance", json={"months": 3}).status_code == 409


def test_a_turn_returns_only_once_the_whole_quarter_has_been_played():
    """The browser must never be handed a half-played turn.

    The harness steps a month at a time, so an `/advance` that returned as soon as the tick moved
    came back one month into a three month quarter: the canvas drew a city mid-turn, and the turn
    counter beside it was a turn behind. Both symptoms of the same race, and both invisible unless
    the tick is checked against the turn length.
    """
    harness = RunHarness(SHORT)
    prepared = harness.prepare()
    controller = HumanController(turn_budget=SHORT.turn_budget)
    session = _session(controller, prepared)
    client = TestClient(create_app(session))
    start = prepared.state.tick

    seen: list[tuple[int, int]] = []

    def play() -> None:
        for _ in range(SHORT.turn_budget):
            body = client.post("/advance", json={"months": 3}).json()
            seen.append((body["state"]["tick"], body["state"]["progress"]["turns_played"]))

    player = threading.Thread(target=play, daemon=True)
    player.start()
    harness.run(controller, mode="human", prepared=prepared)
    controller.finish()
    player.join(timeout=30)

    # Whole quarters only, and the turn count agrees with the clock every time.
    assert seen == [
        (start + SHORT.months_per_turn * n, n) for n in range(1, SHORT.turn_budget + 1)
    ]


def test_the_last_turn_reports_the_run_as_over_in_its_own_response():
    """The browser should not have to poll again to notice the run ended.

    `controller.finish()` runs on the harness thread after `run()` returns, which is a moment after
    the final month lands. Reading completion from the clock as well means the reply to the last
    `/advance` already says so.
    """
    harness = RunHarness(SHORT)
    prepared = harness.prepare()
    controller = HumanController(turn_budget=SHORT.turn_budget)
    client = TestClient(create_app(_session(controller, prepared)))
    last: dict = {}

    def play() -> None:
        for _ in range(SHORT.turn_budget):
            last.update(client.post("/advance", json={"months": 3}).json())

    player = threading.Thread(target=play, daemon=True)
    player.start()
    harness.run(controller, mode="human", prepared=prepared)
    player.join(timeout=30)

    assert last["state"]["progress"]["complete"] is True


def test_a_scored_run_cannot_be_reset_but_free_play_can():
    """Reset mid-run would leave the harness stepping a city the browser no longer shows."""
    prepared = RunHarness(SHORT).prepare()
    controller = HumanController(turn_budget=SHORT.turn_budget)
    human = TestClient(create_app(_session(controller, prepared)))
    assert human.post("/reset", json={}).status_code == 409

    sandbox = TestClient(create_app(SimSession(seed=42)))
    assert sandbox.post("/reset", json={}).status_code == 200


def test_the_briefing_reaches_the_browser_and_free_play_gets_none():
    prepared = RunHarness(SHORT).prepare()
    controller = HumanController(turn_budget=SHORT.turn_budget)
    briefing = {"index": 0.34, "green_threshold": 0.62}
    human = TestClient(create_app(_session(controller, prepared, briefing=briefing)))
    state = human.get("/state").json()
    assert state["briefing"]["index"] == 0.34
    assert state["progress"]["turn_budget"] == SHORT.turn_budget
    assert state["progress"]["complete"] is False

    sandbox = TestClient(create_app(SimSession(seed=42))).get("/state").json()
    assert "briefing" not in sandbox
    assert "progress" not in sandbox


def test_the_scene_still_carries_no_measurement_of_the_city():
    """The briefing is a fixed opening snapshot in the help panel, not a dashboard.

    `/scene` is what the canvas draws every tick. A health number reaching it would be a live
    readout, which is the thing the whole no-numbers rule exists to prevent -- and it would break
    the parity that `agent_*` modes are scored under.
    """
    prepared = RunHarness(SHORT).prepare()
    controller = HumanController(turn_budget=SHORT.turn_budget)
    session = _session(controller, prepared, briefing={"index": 0.34})
    scene = TestClient(create_app(session)).get("/scene").json()

    banned = {"index", "health", "solvency", "satisfaction", "service", "population", "treasury"}
    assert not banned & set(scene)
    for building in scene["buildings"][:20]:
        assert not banned & set(building)


def test_a_briefed_human_is_exempt_from_the_model_parity_check():
    """`human` reports "human", not a model id, and must not trip the mismatch warning."""
    from blindcity.evaluation.compare import ModeSummary, markdown

    summaries = {
        "agent_raw": ModeSummary(mode="agent_raw", runs=1, final_index=[0.64], green_turn=[9],
                                 total_tokens=[1], llm_calls=[1], llm_seconds=[1.0],
                                 sql_queries=[1], models=["gpt-5.6-luna"]),
        "human": ModeSummary(mode="human", runs=1, final_index=[0.70], green_turn=[5],
                             total_tokens=[0], llm_calls=[0], llm_seconds=[0.0],
                             sql_queries=[0], models=["human"]),
    }
    report = markdown(summaries, threshold=0.62, seed=42, model="gpt-5.6-luna")
    assert "did not run the same model" not in report
