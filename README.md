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

The simulation is also, and mainly, a laboratory. Because we wrote it, we have ground truth. So we
can put a city into the same crisis repeatedly and measure who gets it out — an agent with catalog
context, the same agent without, or a person. No real data team can run that experiment. Their
history only happened once.

## It is a benchmark

The city is the substrate, not the deliverable. A **scenario** puts it into a crisis; a
**controller** pulls levers over a fixed turn budget; a **composite health index** scores whether it
got back into the green in time. Three controllers face the identical seed, crisis, and budget:

| Arm | Who is deciding | What they can see |
| --- | --- | --- |
| `human` | You | The city, the levers, and the Analytics Agent to ask questions |
| `agent_datahub` | Our agent | DataHub over MCP, plus SQL |
| `agent_raw` | Our agent | SQL only — no catalog |

`agent_datahub` vs `agent_raw` measures what the metadata is worth. `human` vs `agent_datahub`
measures what the automation is worth. Every arm gets the same view of the city, so the metadata is
the only thing that varies — which is why there are no numbers on the screen.

## The baseline catalog (control arm)

The A/B comparison needs an honest control: same warehouse, same SQL access, same model and tool
budget — **without** catalog context that would tip the agent toward the right tables and joins.

`uv run datahub-emit --baseline` emits that control catalog. It has:

| Present | Absent |
| --- | --- |
| Table and column *names* (typed schema only) | Descriptions on tables or columns |
| | Glossary terms |
| | Lineage (causal graph) |
| | Assertions |

Table names are deliberately opaque in the style of a rushed legacy ETL dump, not gibberish and not
the semantic names the full catalog uses:

| Full catalog | Baseline (control) |
| --- | --- |
| `citizen_monthly` | `t_person_m` |
| `budget_monthly` | `t_budg_m` |
| `lever_monthly` | `t_policy_m` |
| `road_monthly` | `t_road_m` |
| `power_monthly` | `t_pwr_m` |
| `water_monthly` | `t_h2o_m` |
| `migration_monthly` | `t_mig_m` |
| … | … |

**Why this is fair, not rigged.** A real uncatalogued warehouse still has *some* names — usually
abbreviated, inconsistent, and undocumented. An agent with SQL alone can still `SELECT` from
`t_person_m`; it just has to rediscover what the columns mean and how tables relate. Giving the
control arm random UUIDs or empty schemas would make the comparison a strawman. Giving it the full
glossary and lineage would erase the treatment. Opaque-but-queryable names with no docs is the
honest middle: the only thing that differs between `agent_datahub` and `agent_raw` is metadata
context, which is the quantity under measurement.

The mapping lives in `blindcity.catalog.schema_spec` (`TableSpec.baseline_name`).

## Requirements

- 16 GB RAM or more. DataHub's quickstart alone wants 8 GB plus 2 GB swap.
- 25 GB free disk.
- Docker.
- Python 3.11 or newer, and [`uv`](https://docs.astral.sh/uv/).

## Getting started

```bash
datahub docker quickstart
```

DataHub Core comes up on `localhost:9002` (login `datahub` / `datahub`), with its GraphQL API on
`localhost:8080/api/graphql`. Authentication is off by default, so no token is required.

Full setup — installing `uv` and the DataHub CLI, starting Docker, and the checks that confirm it all
works — is in `docs/ENVIRONMENT.md`. Further application commands land in `AGENTS.md` as the
toolchain settles.

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
- `docs/ENVIRONMENT.md` — verified setup, running topology, credentials
- `docs/ERRORS.md` — problems and resolutions
- `.tasks/mvp/TASKS.md` — current state and the remaining plan

## License

Apache 2.0.
