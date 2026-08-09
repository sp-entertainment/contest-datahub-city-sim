"""Run harness: drive a controller through a scenario turn by turn.

Records per-turn health index, components, and lever settings. Optionally writes
warehouse history under a dedicated run_id without truncating other runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from blindcity.benchmark.controller import Controller, merge_levers
from blindcity.benchmark.health import GREEN_THRESHOLD, health_index, is_green
from blindcity.benchmark.results import RunResult, TurnRecord
from blindcity.benchmark.scenario import Scenario, build_crisis_state, clone_state
from blindcity.rng import RNG
from blindcity.sim.model import CityState
from blindcity.sim.systems import step_month


@dataclass
class PreparedRun:
    """A scenario materialised and, optionally, its history written to the warehouse.

    Exists so a controller can be constructed *against the warehouse run it will read*. The
    agent modes need the `run_id` before their first decision — they diagnose the city through
    SQL scoped to that run — and the harness is what mints it. Without this split the controller
    would have to be built before the run existed.
    """

    state: CityState
    baseline_population: int
    parent: RNG
    durable_id: str
    warehouse_run_id: int | None = None
    writer: Any | None = None


@dataclass
class RunHarness:
    scenario: Scenario
    green_threshold: float = GREEN_THRESHOLD

    def prepare(
        self,
        *,
        run_id: str | None = None,
        warehouse_conn: Any | None = None,
        write_warehouse: bool = False,
        write_crisis_history: bool = True,
    ) -> PreparedRun:
        """Build the crisis city, and record how it got that way.

        `write_crisis_history` writes the months of neglect preceding turn 0. It is on by default
        because an agent that can only see the recovery period cannot diagnose what caused the
        crisis — the evidence is all in the past.
        """
        writer = None
        warehouse_run_id: int | None = None
        durable_id = run_id or str(uuid.uuid4())

        if write_warehouse and warehouse_conn is not None:
            from blindcity.sim.city_init import GRID_H, GRID_W
            from blindcity.sim.warehouse import WarehouseWriter, start_run

            warehouse_run_id = start_run(
                warehouse_conn,
                self.scenario.seed,
                years=0,  # recovery-only horizon recorded loosely
                grid_w=GRID_W,
                grid_h=GRID_H,
            )
            durable_id = str(warehouse_run_id)
            writer = WarehouseWriter(warehouse_conn, warehouse_run_id)

        on_month = None
        if writer is not None and write_crisis_history:
            on_month = writer.write_month

        state, baseline_pop = build_crisis_state(self.scenario, on_month=on_month)
        # Isolate from any caller that reuses the builder
        state = clone_state(state)
        if writer is not None:
            writer.flush_all()

        return PreparedRun(
            state=state,
            baseline_population=baseline_pop,
            # Streams inside step_month fold `state.tick` into the name, so the parent is only
            # a namespace (same pattern as engine.run_simulation).
            parent=RNG(self.scenario.seed),
            durable_id=durable_id,
            warehouse_run_id=warehouse_run_id,
            writer=writer,
        )

    def run(
        self,
        controller: Controller,
        *,
        mode: str = "scripted",
        channel: dict[str, Any] | None = None,
        run_id: str | None = None,
        warehouse_conn: Any | None = None,
        write_warehouse: bool = False,
        prepared: PreparedRun | None = None,
    ) -> RunResult:
        """Execute the scenario under `controller`.

        If `write_warehouse` is True, `warehouse_conn` must be an open psycopg connection
        with schema present. Rows are appended under a new sim_run id; nothing is truncated.
        Pass `prepared` to reuse a run built earlier by `prepare()`.
        """
        if prepared is None:
            prepared = self.prepare(
                run_id=run_id,
                warehouse_conn=warehouse_conn,
                write_warehouse=write_warehouse,
                # Preserves the pre-existing behaviour for scripted callers, which do not read
                # the warehouse and do not need 60 months of setup written for them.
                write_crisis_history=False,
            )
            if prepared.writer is not None:
                prepared.writer.write_month(prepared.state)

        state = prepared.state
        baseline_pop = prepared.baseline_population
        parent = prepared.parent
        durable_id = prepared.durable_id
        writer = prepared.writer
        warehouse_run_id = prepared.warehouse_run_id

        channel = dict(channel or {})
        turns: list[TurnRecord] = []
        green_turn: int | None = None

        for turn in range(self.scenario.turn_budget):
            decision = controller.decide(state, turn, channel)
            state.levers = merge_levers(state.levers, decision)

            for _ in range(self.scenario.months_per_turn):
                step_month(state, parent.stream("tick"))
                if writer is not None:
                    writer.write_month(state)

            components = health_index(state, baseline_pop)
            green = is_green(components, self.green_threshold)
            if green and green_turn is None:
                green_turn = turn

            turns.append(
                TurnRecord(
                    turn=turn,
                    tick=state.tick,
                    levers=dict(state.levers),
                    components=components.to_dict(),
                    index=components.index,
                    green=green,
                )
            )

        if writer is not None:
            writer.finish(years=0)
            writer.flush_all()

        final = turns[-1].index if turns else 0.0
        return RunResult(
            scenario_name=self.scenario.name,
            seed=self.scenario.seed,
            controller_name=getattr(controller, "name", type(controller).__name__),
            mode=mode,
            run_id=durable_id,
            turn_budget=self.scenario.turn_budget,
            green_threshold=self.green_threshold,
            baseline_population=baseline_pop,
            recovered=green_turn is not None,
            green_turn=green_turn,
            final_index=final,
            turns=turns,
            meta={
                "crisis_months": self.scenario.crisis_months,
                "months_per_turn": self.scenario.months_per_turn,
                "warehouse_run_id": warehouse_run_id,
            },
        )


def run_scenario(
    scenario: Scenario,
    controller: Controller,
    **kwargs: Any,
) -> RunResult:
    return RunHarness(scenario).run(controller, **kwargs)


def advance_state(state: CityState, months: int, seed: int, start_tick_stream: int) -> None:
    """Advance an existing state `months` steps using streams as if tick continued."""
    parent = RNG(seed)
    for i in range(start_tick_stream):
        parent.stream("tick")
    for _ in range(months):
        step_month(state, parent.stream("tick"))
