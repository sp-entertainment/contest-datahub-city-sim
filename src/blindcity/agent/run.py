"""Drive one agent arm through one scenario.

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
from blindcity.sim.warehouse import connect, ensure_schema

# The two arms. `context` is the only field that differs, and it is the only field that may.
ARMS: dict[str, str] = {
    "agent_datahub": "datahub",
    "agent_raw": "none",
}


@dataclass
class ArmRun:
    result: RunResult
    report: dict[str, Any]
    wall_seconds: float


def run_arm(
    arm: str,
    *,
    scenario: Scenario = INFRASTRUCTURE_CRISIS,
    model: str | None = None,
    turns: int | None = None,
    tool_budget: int = DEFAULT_TOOL_BUDGET,
    llm: LLM | None = None,
    keep_views: bool = False,
    write_back_findings: bool = True,
) -> ArmRun:
    """Play one arm. `turns` truncates the scenario for smoke tests; None plays it in full."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {sorted(ARMS)}")

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
    # One factory for both arms: they cannot end up on different providers or models.
    client = llm or build_llm(model=model)

    # Two connections on purpose. The writer bulk-loads with COPY against the real tables in
    # `public`; the agent reads through a per-run view schema with `search_path` pointed at it.
    # Sharing one connection sends the writer's COPY into a view, which Postgres refuses.
    conn = connect()
    agent_conn = connect()
    started = time.perf_counter()
    warehouse_run_id: int | None = None
    try:
        ensure_schema(conn)
        prepared = harness.prepare(warehouse_conn=conn, write_warehouse=True)
        assert prepared.warehouse_run_id is not None
        warehouse_run_id = prepared.warehouse_run_id

        controller = AgentController(
            name=arm,
            llm=client,
            conn=agent_conn,
            run_id=warehouse_run_id,
            catalog=build_catalog(ARMS[arm]),
            tool_budget=tool_budget,
            turn_budget=scenario.turn_budget,
        )
        result = harness.run(controller, arm=arm, prepared=prepared)
        report = controller.report()

        # After scoring, never before: write-back must not be able to influence the run it
        # describes. The control arm is skipped inside `write_back` rather than here, so the
        # decision stays in one place and no branch on the arm enters this loop.
        if write_back_findings:
            report["write_back"] = writeback.write_back(report, str(result.run_id)).to_dict()
    finally:
        # The per-run views are scaffolding, not data. The rows they read stay in the warehouse
        # under their run_id; only the schema of views goes. Keep them with --keep-views when
        # you want to poke at exactly what the agent could see.
        if warehouse_run_id is not None and not keep_views:
            try:
                runscope.drop_run_views(conn, warehouse_run_id)
            except psycopg.Error:
                pass  # cleanup only; never mask the real outcome of the run
        agent_conn.close()
        conn.close()

    wall = time.perf_counter() - started
    result.meta["agent"] = report
    result.meta["wall_seconds"] = round(wall, 1)
    return ArmRun(result=result, report=report, wall_seconds=wall)


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
