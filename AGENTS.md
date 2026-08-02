# Agent Instructions — Blind City

## Vision statement

> Immutable. Read it, never modify it.

Imagine a Sim City / transportation simulation game where there is no user-facing UI telling the
user what to do, whether the economy's going up or down, whether their income is going up or down,
how it's trending. The simulation itself is producing reams of data in a directory: tons of detailed
data about the citizens, what they're doing, their stats, data about the roads, road conditions over
time, sewers, water, electricity, electricity rates from the power companies, how much electricity is
needed, etc. Tons upon tons of data that will take a regular human a long time to sift through.

You're looking at the screen, a simulated city producing reams of data. The only thing you can do on
your screen is pull certain levers, certain actions that will affect the city, increasing taxes,
decreasing taxes, that sort of thing. This is where DataHub comes in. DataHub connects to the data
that the city is generating and you can query it, ask the data questions: "Should I raise income
taxes?" DataHub will be smart enough to look at the data, see the trends, and give you the best
guidance.

DataHub is essentially a stand-in for what the normal game UI would be. It would do what it would
signal to the user.

## Contest context

- **Event:** Build with DataHub: The Agent Hackathon (Devpost).
- **Deadline:** 2026-08-10, 5:00pm EDT.
- **Required license:** Apache 2.0 on the public submission repository.
- **Deliverables:** working project URL, public Apache-2.0 repo, text description, demo video under
  three minutes, optional sample outputs.
- **Judged on:** depth of DataHub use, technical execution, originality, real-world usefulness,
  submission quality. Bonus for upstream contributions to DataHub.

## Project map

```
src/blindcity/
  sim/         Headless deterministic city simulation. Writes rows to Postgres.
               Also emits its own causal graph as a lineage artifact.
  catalog/     Metadata ingestion: schemas, glossary terms, lineage, assertions.
  agent/       Auto-mode agent. DataHub MCP + SQL + lever actuation, closed loop.
  evaluation/  A/B harness: agent with DataHub context vs without, same seed.
  levers.py    The eight levers. Single source of truth for ranges and defaults.
  rng.py       Seeded randomness. Determinism is a hard rule.
  config.py    Connection settings.
viewer/        Canvas tile map and lever panel. No numbers, no charts, no trends.
infra/         Docker compose for the warehouse Postgres.
tests/         pytest.
docs/          See document map below.
```

Two naming notes, both deliberate:

- **`catalog/`, not `datahub/`.** A top-level `datahub` package would shadow the installed
  `acryl-datahub` module and break every import of the DataHub SDK.
- **`evaluation/`, not `eval/`.** Avoids a module named after a builtin. The *command* is still
  `uv run eval`.

Manual mode uses the upstream `datahub-analytics-agent` unmodified. Auto mode is our own agent and is
the original contribution.

### Runtime topology

Everything runs on one machine. DataHub Core via `datahub docker quickstart` (six containers as of
plan `v1.5.0.6`), Postgres as the warehouse in its own container on 5432, sim exposing a small
FastAPI control surface, Analytics Agent on `:8100`.

DataHub's own metadata store is MySQL on 3306 and is not the warehouse. See `docs/ENVIRONMENT.md`.

Auth stays off. DataHub OSS quickstart accepts unauthenticated writes to
`localhost:8080/api/graphql`, so no access token is needed.

## Document map

- `AGENTS.md` — this file. Vision, contest constraints, project map, conventions.
- `README.md` — human onboarding, dependencies, commands.
- `CONTRIBUTING.md` — contribution and commit conventions.
- `docs/FEATURES.md` — what the product does, feature by feature.
- `docs/ENVIRONMENT.md` — verified setup commands, running topology, credentials, lifecycle.
- `docs/DECISIONS.md` — append-only decision log with context and rationale.
- `docs/ERRORS.md` — problems hit and how they were resolved.
- `.tasks/<work-item>/TASKS.md` — plan and status for multi-step work.

## Commands

> Fill in as the toolchain lands. Placeholders are intentional, not decoration. A command is moved
> above the line only once it has been run and observed to work.

**Verified.** Setup and verification commands, with observed results, are in `docs/ENVIRONMENT.md`.

**Not yet verified.** Everything below is the intended shape, not a working command.

```bash
# DataHub Core — verified, see docs/ENVIRONMENT.md
datahub docker quickstart

# Simulation
uv run sim --seed 42 --years 20

# Metadata ingestion
uv run datahub-emit

# Agent, auto mode
uv run agent --mode auto

# Evaluation
uv run eval --seeds 5
```

## Conventions

- **Python 3.11+, managed with `uv`.** The Analytics Agent requires 3.11 or newer.
- **Apache 2.0 headers stay intact.** No GPL code enters this repository. That rules out
  OpenTTD and Micropolis derivatives.
- **The simulation is deterministic.** Same seed produces the same city, always. The A/B evaluation
  is meaningless otherwise.
- **Lineage is generated, never hand-authored.** It is derived from the simulation's own equations.

## Dos and don'ts

- **Do set `TOOLS_IS_MUTATION_ENABLED=true`** in the MCP config. Mutation tools are not registered at
  all without it, so they never appear in the tool list.
- **Do keep the baseline honest.** The no-DataHub control gets the same model, prompt, seed, tool
  budget, and full SQL access. Only the metadata context differs.
- **Don't build a dashboard.** Any chart or trend line in the viewer defeats the premise.
- **Don't ship only the upstream Analytics Agent.** Originality is a judged criterion; the closed
  loop is ours.
