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
- **Control modes.** Five controllers implement one interface and face identical conditions:
  - `human` — a person, with the city render, the levers, and the Analytics Agent to ask questions.
    `blindcity run --mode human` prepares the identical crisis, serves the city on `:8000` and is
    then driven entirely from the browser; the harness scores it like any other mode.
  - `agent_raw` — our auto-mode agent with SQL only and no catalog context.
  - `agent_datahub` — the same agent, plus DataHub descriptions, glossary and column lineage.
  - `agent_datahub_live` — the same again, plus assertions read from DataHub each turn.
  - `agent_analytics` — DataHub's own Analytics Agent answers the questions instead, reading
    DataHub and the warehouse through its own tools.
  - `good_policy` and `bad_policy` — fixed lever sets that call no model, as references either side.
- **Results.** Per-run health trajectory, turn at which green was reached (if ever), lever history,
  and the component breakdown. `agent_datahub` vs `agent_raw` measures descriptive metadata;
  `agent_datahub_live` vs `agent_datahub` measures prescriptive metadata; `human` vs the agents
  measures the automation.
- **Full transcripts.** Every agent run writes the system prompt, the complete conversation as the
  model received it, and every reply, beside its result file.
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

Authored as code in `src/blindcity/catalog/`, published to DataHub, and read back from DataHub at
run time — the catalog is a serving layer, not a mirror of a local file.

- **Schema publication.** Every warehouse table and column published to DataHub with a description.
- **Glossary.** Every city concept defined once, centrally, and attached to the columns that mean it.
- **Generated lineage.** The simulation's causal graph, emitted as DataHub lineage at table and
  column level. Each edge is proven by experiment before it ships (`sim/causal_check.py`).
- **Assertions.** Quality and range expectations on simulation outputs, **evaluated as SQL** against
  the warehouse (`blindcity emit --evaluate-assertions`) with pass/fail emitted beside the metadata.
- **Operating guidance.** Per-lever bands, impact ratings and notes, published as dataset custom
  properties and fetched back by the agent each turn.

## Control surface

- **FastAPI** on `uv run blindcity sim --serve`: `GET /state`, `POST /lever`, `POST /advance`, `GET /scene`.
- **`GET /scene`** returns tiles, buildings, roads, citizens for rendering — no population totals,
  treasury, or health aggregates (information parity).
- **Static `viewer/`** served from the same process.

## Agents

- **Auto mode.** Closed loop — read state, gather context, query Postgres, decide, actuate levers,
  advance, observe. One implementation instantiated as `agent_raw`, `agent_datahub` and
  `agent_datahub_live`; the three differ only in the catalog block, and `tests/test_agent.py` fails
  the build if anything else about their prompts, tools or turn messages diverges.
- **Advisor mode.** `agent_analytics` hands the analysis to the upstream DataHub Analytics Agent
  running as its own service, and acts on what it answers. Model parity between the service and the
  other modes is checked at run time by `preflight()`.
- **Write-back.** After a run the agent records what it found back into the catalog, rather than
  keeping the knowledge in a transcript nobody reads.

## Evaluation

- **Multi-mode comparison** on identical seed, crisis, and turn budget, folded into one table by
  `blindcity compare`.
- **Reported per mode:** health index trajectory, turn green was reached, whether it was reached at
  all, lever history, and the index components.
- **Provenance in the report.** Model, seed, threshold and git commit are read back out of the
  recorded runs, so a number can be traced to the code that produced it.
