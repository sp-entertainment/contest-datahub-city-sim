# Blind City

A city simulation with no interface.

The city runs. It produces enormous volumes of data — citizens, households, roads, power, water,
sewer, budget. Your screen shows the city and eight levers. Nothing else. No charts, no counters, no
warnings, no trends.

To find out what is happening, you ask an agent. The agent uses [DataHub](https://datahub.com) to
learn what data exists, what it means, and how it connects, then queries the warehouse and answers
you. The catalog and the agent, together, replace the interface.

Built for [Build with DataHub: The Agent Hackathon](https://datahub.devpost.com/).

## The idea

Every game interface does two jobs: it finds the relevant numbers among everything the engine tracks,
and it explains what they mean. That is precisely what a metadata catalog does. So we removed the
interface and pointed an agent at the catalog instead.

The simulation is also, quietly, a laboratory. Because we wrote it, we have ground truth. So we can
run the same agent twice on the same seed — once with DataHub context, once with nothing but raw
schemas — and measure whether metadata context actually produces better decisions. No real data team
can run that experiment. Their history only happened once.

## Modes

- **Manual.** You ask questions, you read answers, you pull the levers.
- **Auto.** The agent reads the city, decides, pulls a lever, and lives with the consequence.

## Requirements

- 16 GB RAM or more. DataHub's quickstart alone wants 8 GB plus 2 GB swap.
- 25 GB free disk.
- Docker.
- Python 3.11 or newer, and [`uv`](https://docs.astral.sh/uv/).

## Getting started

```bash
datahub docker quickstart
```

DataHub Core comes up on `localhost:9002`, with its GraphQL API on `localhost:8080/api/graphql`.
Authentication is off by default, so no token is required.

Further commands land in `AGENTS.md` as the toolchain settles.

## Architecture

```
sim  ──rows──────────>  Postgres  <──SQL──┐
 │                                        │
 └──generated lineage──>  DataHub  <──MCP──┤
                                          │
                          manual mode:  Analytics Agent  ──> you ──> levers
                          auto mode:    our agent  ────────────────> levers
```

The simulation emits its own causal graph as DataHub lineage. Tax rate feeds disposable income, feeds
migration, feeds population, feeds revenue, feeds tax rate. The agent traverses that graph to reason
about consequences before it answers.

## Documentation

- `AGENTS.md` — vision, constraints, conventions
- `docs/FEATURES.md` — what it does
- `docs/DECISIONS.md` — why it is built this way
- `docs/ERRORS.md` — problems and resolutions

## License

Apache 2.0.
