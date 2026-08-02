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

The player's whole window onto the city. It must look like a city — a place, populated and alive —
not a debug view of a data structure.

- **Rendered city scene.** Zoning and buildings drawn as buildings, roads as roads, the power grid
  and water and sewer network visible as infrastructure. The city grows, densifies, and decays
  visibly as the simulation runs.
- **Visible inhabitants.** Citizens rendered in the scene, moving between homes and workplaces on
  the road network. The city is populated, and the population is something you watch rather than
  something you read.
- **Visible condition.** Road wear shows as damaged road. A power shortfall shows as dark buildings.
  Abandonment shows as derelict lots. Congestion shows as congestion. The player perceives the
  city's state the way they would looking out a window.
- **Lever panel.** The eight controls as real GUI inputs in manual mode — sliders and selectors the
  player manipulates directly, showing the current position of each lever.
- **No instrumentation.** No charts, no trend lines, no counters, no gauges, no alerts, no numeric
  readouts of city state. Deliberate, and the line is sharp: **showing the city is the product;
  showing measurements of the city is the thing we removed.** A visibly potholed road is the city.
  A "road quality: 34%" label is instrumentation. Lever positions are the exception — those are the
  player's own inputs, not the simulation's state.

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
