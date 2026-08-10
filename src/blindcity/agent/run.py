"""Drive one agent mode through one scenario.

The order here matters and is the reason `RunHarness.prepare` exists: the warehouse run must be
created and the crisis history written *before* the controller is built, because the controller
reads the city through SQL scoped to that run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import psycopg

from blindcity.agent import runscope, writeback
from blindcity.agent.catalog import build_catalog
from blindcity.agent.controller import DEFAULT_TOOL_BUDGET, AgentController
from blindcity.agent.llm import LLM, build_llm
from blindcity.agent.monitor import build_monitor
from blindcity.agent.transcript import RecordingLLM
from blindcity.benchmark.harness import RunHarness
from blindcity.benchmark.results import RunResult
from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS, Scenario
from blindcity.sim.warehouse import (
    WarehouseInUse,
    connect,
    ensure_schema,
    reset_warehouse,
    runs_in_flight,
)

# The modes, as (catalog, monitor). Three points on one line rather than one changed number:
# `agent_raw` has no catalog, `agent_datahub` has the static one, `agent_datahub_live` adds the
# per-turn assertion check. Keeping the first two untouched means the original comparison stands
# on its own and the third can be read as an increment to it.
MODES: dict[str, tuple[str, str]] = {
    "agent_datahub": ("datahub", "none"),
    "agent_raw": ("none", "none"),
    "agent_datahub_live": ("datahub", "assertions"),
}

# Not one of the above, because it is not our agent at all. `agent_analytics` delegates the whole
# analysis to DataHub's Analytics Agent running as a separate service, and asks it in plain English
# which levers to move. It shares the scenario, the seed, the turn budget and the lever set, so its
# score is comparable -- but it does not share the controller, so it cannot share their parity
# guarantee, and it is reported as a separate line rather than a fourth point on the same axis.
ADVISOR_MODE = "agent_analytics"

# The calibrated reference policies, playable through the same runner as everything else. They are
# fixed lever sets rather than agents: `good_policy` is what the scenario looks like handled well,
# `bad_policy` is continued neglect, and between them they show the crisis is both winnable and
# losable. Neither calls a model, so both are free.
#
# They were a separate `eval --dry-run` code path until 2026-08-10. Folding them in means there is
# exactly one way to play a scenario and one way to write a result -- the reference numbers are
# produced by the same harness, scoring and file format as the scores they are the yardstick for,
# rather than by a parallel path that could drift away from it.
SCRIPTED_MODES: dict[str, str] = {
    "good_policy": "good_recovery",
    "bad_policy": "bad_neglect",
}

# Everything `--mode` accepts, in the order a reader wants them.
ALL_MODES: tuple[str, ...] = (*MODES, ADVISOR_MODE, *SCRIPTED_MODES)


@dataclass
class ModeRun:
    result: RunResult
    report: dict[str, Any]
    wall_seconds: float


@dataclass
class _ScriptedRun:
    """Wraps a fixed-lever controller so it reports like every other mode.

    `compare` reads `usage`, `turns` and the failure counters out of each run's sidecar. A
    reference policy that omitted them would need a special case in the reporting path, which is
    exactly the kind of second code path this consolidation exists to remove -- so it reports zeros
    and an empty turn list rather than nothing. The zeros are true: no model was called.
    """

    name: str
    inner: Any

    def decide(self, state: Any, turn: int, channel: dict[str, Any]) -> dict[str, float]:
        return self.inner.decide(state, turn, channel)

    def report(self) -> dict[str, Any]:
        return {
            "controller": self.name,
            "model": "scripted",
            "catalog": "none",
            "monitor": "none",
            "turns": [],
            "usage": {
                "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "calls": 0, "seconds": 0.0,
            },
            "tool_failures": 0,
            "timeouts": 0,
            "infrastructure_failures": 0,
        }


def run_mode(
    mode: str,
    *,
    scenario: Scenario = INFRASTRUCTURE_CRISIS,
    model: str | None = None,
    turns: int | None = None,
    tool_budget: int = DEFAULT_TOOL_BUDGET,
    llm: LLM | None = None,
    keep_views: bool = False,
    write_back_findings: bool = True,
    clean_warehouse: bool = True,
    force_clean: bool = False,
    transcript: str | None = None,
    advisor_url: str | None = None,
) -> ModeRun:
    """Play one mode. `turns` truncates the scenario for smoke tests; None plays it in full."""
    if mode not in ALL_MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(ALL_MODES)}")

    if turns is not None and turns < scenario.turn_budget:
        # Only the horizon changes. Seed, crisis, levers and shock are untouched, so a truncated
        # run is a genuine prefix of the full one rather than a different scenario.
        scenario = Scenario(
            name=scenario.name,
            seed=scenario.seed,
            crisis_months=scenario.crisis_months,
            turn_budget=turns,
            months_per_turn=scenario.months_per_turn,
            crisis_levers=scenario.crisis_levers,
            description=scenario.description,
        )

    harness = RunHarness(scenario)
    # One factory for every agent mode: they cannot end up on different providers or models.
    #
    # Built lazily, because the scripted reference policies call no model and must stay runnable
    # with no API key and no network -- that is what makes them a yardstick anyone can reproduce
    # from a clone. `build_llm` raises when LLM_MODEL is unset, so constructing it here
    # unconditionally would make the free path require a paid one.
    client: Any = None
    if mode not in SCRIPTED_MODES:
        client = llm or build_llm(model=model)
        if transcript:
            # Wrapped last, so the recording is of exactly what the controller sent.
            client = RecordingLLM(client, transcript, mode=mode)

    # Two connections on purpose. The writer bulk-loads with COPY against the real tables in
    # `public`; the agent reads through a per-run view schema with `search_path` pointed at it.
    # Sharing one connection sends the writer's COPY into a view, which Postgres refuses.
    conn = connect()
    agent_conn = connect()
    started = time.perf_counter()
    warehouse_run_id: int | None = None
    try:
        phase_start = time.perf_counter()
        ensure_schema(conn)
        if clean_warehouse:
            # Every run starts from an empty warehouse. The rows are evidence for one run, not an
            # archive, and a warehouse holding twenty previous cities changes what the planner
            # chooses, how long ANALYZE takes, and how much a mis-scoped query can see -- none of
            # which should differ between two modes that are meant to be identical. Pass
            # keep_warehouse when you need to inspect what an earlier run's agent could see.
            live = runs_in_flight(conn)
            if live and not force_clean:
                raise WarehouseInUse(
                    f"run(s) {live} started recently and have not finished; refusing to clear the "
                    "warehouse under them. Wait for them, or pass force_clean to override."
                )
            # Views first: DROP TABLE CASCADE takes the views but leaves their schemas standing.
            runscope.drop_all_run_views(conn)
            reset_warehouse(conn)
        prepared = harness.prepare(warehouse_conn=conn, write_warehouse=True)
        # Statistics must exist before the agent queries, or the planner will choose nested
        # loops over hundreds of thousands of rows and every interesting query will time out.
        runscope.analyze_run_tables(conn)
        # Sweep view schemas orphaned by earlier runs that were killed mid-flight.
        runscope.drop_stale_run_views(conn, keep=prepared.warehouse_run_id)
        prepare_seconds = time.perf_counter() - phase_start
        assert prepared.warehouse_run_id is not None
        warehouse_run_id = prepared.warehouse_run_id

        controller: Any
        if mode in SCRIPTED_MODES:
            # A fixed lever set played through the same harness as every agent mode. It reports
            # like one too -- an empty usage block rather than no usage block -- so `compare` does
            # not need a branch for the reference rows.
            from blindcity.benchmark.controller import bad_controller, good_controller

            builder = good_controller if mode == "good_policy" else bad_controller
            controller = _ScriptedRun(mode, builder())
        elif mode == ADVISOR_MODE:
            from blindcity.agent.advisor import AnalyticsAgentAdvisor
            from blindcity.agent.advisor_controller import AdvisorController

            advisor = AnalyticsAgentAdvisor(advisor_url)
            # Checked before a single turn is played, so a misconfigured advisor fails loudly
            # instead of producing a score that is quietly not comparable.
            advisor.preflight(expected_model=client.model)
            controller = AdvisorController(
                name=mode,
                advisor=advisor,
                turn_budget=scenario.turn_budget,
                # This mode never touches `RecordingLLM`, because it never calls a model itself.
                # Without this it produced a 0-byte transcript beside a run that spent 1.2M
                # tokens -- the most expensive mode in the benchmark, and the only one whose
                # artifacts said nothing had been said.
                transcript=transcript,
            )
        else:
            controller = AgentController(
                name=mode,
                llm=client,
                conn=agent_conn,
                run_id=warehouse_run_id,
                catalog=build_catalog(MODES[mode][0]),
                monitor=build_monitor(MODES[mode][1]),
                tool_budget=tool_budget,
                turn_budget=scenario.turn_budget,
                reconnect=connect,
            )
        phase_start = time.perf_counter()
        result = harness.run(controller, mode=mode, prepared=prepared)
        play_seconds = time.perf_counter() - phase_start
        report = controller.report()
        report["phases"] = {
            "prepare_seconds": round(prepare_seconds, 1),
            "play_seconds": round(play_seconds, 1),
        }

        # After scoring, never before: write-back must not be able to influence the run it
        # describes. The control mode is skipped inside `write_back` rather than here, so the
        # decision stays in one place and no branch on the mode enters this loop.
        if write_back_findings and mode != ADVISOR_MODE and mode not in SCRIPTED_MODES:
            report["write_back"] = writeback.write_back(report, str(result.run_id)).to_dict()
    finally:
        # Close the agent's connection FIRST. It is the one that read through the views, and
        # DROP SCHEMA CASCADE needs a lock that connection may still hold. Dropping before
        # closing it makes the cleanup wait on a lock held by a session the cleanup itself is
        # keeping alive -- a self-deadlock that stalled a completed run for 27 minutes.
        agent_conn.close()
        # The per-run views are scaffolding, not data. The rows they read stay in the warehouse
        # under their run_id; only the schema of views goes. Keep them with --keep-views when
        # you want to poke at exactly what the agent could see.
        if warehouse_run_id is not None and not keep_views:
            try:
                runscope.drop_run_views(conn, warehouse_run_id)
            except psycopg.Error:
                pass  # cleanup only; never mask the real outcome of the run
        conn.close()

    wall = time.perf_counter() - started
    result.meta["agent"] = report
    result.meta["wall_seconds"] = round(wall, 1)
    return ModeRun(result=result, report=report, wall_seconds=wall)


def estimate_full_run(report: dict[str, Any], turns_played: int, turn_budget: int) -> dict[str, Any]:
    """Extrapolate a full scenario from a truncated smoke test, for budgeting H3.

    Deliberately linear and slightly pessimistic about nothing: per-turn cost is roughly flat
    because each turn starts a fresh conversation rather than accumulating one. If that changes,
    this estimate stops being valid and the note in the report should change with it.
    """
    usage = report.get("usage", {})
    if turns_played <= 0:
        return {"error": "no turns played"}
    scale = turn_budget / turns_played
    return {
        "turns_measured": turns_played,
        "turn_budget": turn_budget,
        "prompt_tokens": int(usage.get("prompt_tokens", 0) * scale),
        "output_tokens": int(usage.get("output_tokens", 0) * scale),
        "total_tokens": int(usage.get("total_tokens", 0) * scale),
        "llm_calls": int(usage.get("calls", 0) * scale),
        "llm_seconds": round(usage.get("seconds", 0.0) * scale, 1),
    }
