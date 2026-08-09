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

# The two modes. `context` is the only field that differs, and it is the only field that may.
MODES: dict[str, str] = {
    "agent_datahub": "datahub",
    "agent_raw": "none",
}


@dataclass
class ModeRun:
    result: RunResult
    report: dict[str, Any]
    wall_seconds: float


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
) -> ModeRun:
    """Play one mode. `turns` truncates the scenario for smoke tests; None plays it in full."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODES)}")

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
    # One factory for both modes: they cannot end up on different providers or models.
    client = llm or build_llm(model=model)

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

        controller = AgentController(
            name=mode,
            llm=client,
            conn=agent_conn,
            run_id=warehouse_run_id,
            catalog=build_catalog(MODES[mode]),
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
        if write_back_findings:
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
