# Features

## Simulation

- **Deterministic city model.** Seeded, headless, fast-forwardable. Same seed reproduces the same
  city exactly.
- **Citizen agents.** Individuals with households, jobs, income, commute, and satisfaction.
- **Road network.** Segments carrying traffic, accumulating wear, requiring maintenance.
- **Power grid.** Demand, generation, supplier contracts, tariffs, outages.
- **Water and sewer.** Capacity, load, failures.
- **Municipal budget.** Revenue lines, expenditure lines, debt.
- **Migration.** Households arrive and leave in response to conditions.

## Levers

The player's entire control surface. Eight scalars, no other input.

- `income_tax_rate`
- `property_tax_rate`
- `electricity_tariff`
- `road_maintenance_budget`
- `water_sewer_capex`
- `transit_fare`
- `zoning_release`
- `power_contract_mode`

## Benchmark

The point of the project. See `docs/DECISIONS.md`, 2026-08-02.

- **Scenario.** A defined crisis: the city starts in an unhealthy state with a fixed turn budget to
  recover. Same seed, same crisis, same budget for every mode.
- **Health index.** A composite 0–1 score over solvency, citizen satisfaction, service coverage, and
  population retention. "Green" is a threshold on the index; a run succeeds if it crosses green
  within the budget.
- **Control modes.** Three controllers implement one interface and face identical conditions:
  - `human` — a person, with the city render, the levers, and the Analytics Agent to ask questions.
  - `agent_datahub` — our auto-mode agent with DataHub over MCP plus SQL.
  - `agent_raw` — the same agent with SQL only and no catalog context.
- **Results.** Per-run health trajectory, turn at which green was reached (if ever), lever history,
  and the component breakdown. `agent_datahub` vs `agent_raw` measures the metadata;
  `human` vs `agent_datahub` measures the automation.
- **Run isolation.** Modes run in parallel and all write history, so every row carries a run
  identifier and no mode truncates another's data.

## Viewer

Cosmetic, and the human mode's control surface. It is not a faithful representation of the city and
does not need to be.

- **City scene.** Enough to read as a city: an isometric grid, buildings as blocks, roads, citizens
  as dots. Low fidelity by design — see `viewer/README.md`.
- **Lever panel.** The eight controls as real GUI inputs — sliders and selectors showing each
  lever's current position. This part is functional, not cosmetic: without it the human mode cannot
  play.
- **Advance control.** Step the simulation a turn and see what happened.
- **No instrumentation.** No charts, trend lines, counters, gauges, alerts, or numeric readouts of
  city state. This is an experimental control, not a style rule: a number on screen gives the human
  mode an information channel the agent modes do not have and invalidates the comparison. Lever
  positions are the controller's own input and are exempt.

## Metadata layer

- **Schema ingestion.** Warehouse schemas pulled into DataHub automatically.
- **Glossary.** Every city concept defined once, centrally.
- **Generated lineage.** The simulation's causal graph, emitted as DataHub lineage, table and column
  level.
- **Assertions.** Quality and range expectations on simulation outputs, **evaluated as SQL** against
  the warehouse (`blindcity emit --evaluate-assertions`) with pass/fail emitted beside the metadata.

## Control surface

- **FastAPI** on `uv run blindcity sim --serve`: `GET /state`, `POST /lever`, `POST /advance`, `GET /scene`.
- **`GET /scene`** returns tiles, buildings, roads, citizens for rendering — no population totals,
  treasury, or health aggregates (information parity).
- **Static `viewer/`** served from the same process.

## Agents

- **Manual mode.** Upstream Analytics Agent answers questions. This is the tooling the `human` mode
  gets — it does not pull levers itself.
- **Auto mode.** Closed loop — read state, gather context, query Postgres, decide, actuate a lever,
  advance, observe. Runs as `agent_datahub` (with catalog context) and `agent_raw` (without); the
  two modes differ only in that context.
- **Write-back.** The agent records findings into the catalog rather than working around gaps.

## Evaluation

- **Three-mode comparison** on identical seed, crisis, and turn budget.
- **Reported per mode:** health index trajectory, turn green was reached, whether it was reached at
  all, lever history, and the index components.
- **Future, not now.** Seed the simulation from real historical city data so the benchmark runs
  against real conditions.
