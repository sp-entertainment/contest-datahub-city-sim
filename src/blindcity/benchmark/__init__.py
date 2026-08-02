"""Benchmark substrate: scenario, health index, controllers, harness, results.

This package is the product — see docs/DECISIONS.md, 2026-08-02. Agent arms (Slice 6)
implement the controller interface defined here.
"""

from __future__ import annotations

from blindcity.benchmark.controller import (
    Controller,
    FixedLeverController,
    ScriptedController,
)
from blindcity.benchmark.harness import RunHarness, run_scenario
from blindcity.benchmark.health import GREEN_THRESHOLD, WEIGHTS, HealthComponents, health_index
from blindcity.benchmark.results import RunResult
from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS, Scenario

__all__ = [
    "GREEN_THRESHOLD",
    "INFRASTRUCTURE_CRISIS",
    "WEIGHTS",
    "Controller",
    "FixedLeverController",
    "HealthComponents",
    "RunHarness",
    "RunResult",
    "Scenario",
    "ScriptedController",
    "health_index",
    "run_scenario",
]
