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

## Viewer

- **Tile map.** Canvas rendering of the city. Shows the city, not its statistics.
- **Lever panel.** The eight controls.
- **No instrumentation.** No charts, no trend lines, no counters, no alerts. Deliberate.

## Metadata layer

- **Schema ingestion.** Warehouse schemas pulled into DataHub automatically.
- **Glossary.** Every city concept defined once, centrally.
- **Generated lineage.** The simulation's causal graph, emitted as DataHub lineage, table and column
  level.
- **Assertions.** Quality and range expectations on simulation outputs.

## Agents

- **Manual mode.** Upstream Analytics Agent answers the player's questions. The player decides and
  pulls levers.
- **Auto mode.** Closed loop — read state, gather context from DataHub, query Postgres, decide,
  actuate a lever, advance the simulation, observe the consequence.
- **Write-back.** The agent records findings into the catalog rather than working around gaps.

## Evaluation

- **Context A/B.** Identical agent, identical seed, with and without DataHub context.
- **Outcome comparison.** Population, solvency, and citizen satisfaction after twenty simulated
  years.
