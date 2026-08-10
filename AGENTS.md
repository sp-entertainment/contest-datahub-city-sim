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

## What this project is

> The vision statement above is immutable and still describes the premise. This section describes
> the shape the work actually takes — see `docs/DECISIONS.md`, 2026-08-02.

**Blind City is a benchmark for whether catalog metadata improves agent decisions.** It is not a
game, and the city is not the deliverable — it is the substrate that makes the measurement mean
something.

A **scenario** puts the city into a defined crisis. A **controller** pulls levers over a fixed turn
budget. A run is scored by a **composite health index**; "recovered" means the index crossed the
green threshold within the budget. Three controllers face the identical seed, crisis, and budget:

| Mode | Controller | Sees |
| --- | --- | --- |
| `human` | A person | The city render, the levers, and the Analytics Agent to ask questions |
| `agent_datahub` | Our auto-mode agent | DataHub over MCP, plus SQL against the warehouse |
| `agent_raw` | Our auto-mode agent | SQL only, no catalog context |

Two comparisons fall out: `agent_datahub` vs `agent_raw` measures the metadata; `human` vs
`agent_datahub` measures the automation.

**What follows from this.** Simulation fidelity is where effort belongs. The viewer is cosmetic —
it must look like a city and carry the levers, nothing more. Information parity across modes is an
experimental control, so a number on screen is not a style violation, it is a corrupted experiment.

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
               Also declares its causal graph, validated per edge (causal_check.py).
  catalog/     Metadata ingestion: schemas, glossary terms, lineage, assertions.
  agent/       Auto-mode agent. DataHub MCP + SQL + lever actuation, closed loop.
               Runs as both the agent_datahub and agent_raw modes.
  benchmark/   Scenario definition, health index, turn budget, controller interface,
               run harness, results. The measurement, and the point of the project.
  evaluation/  Runs the modes and compares them. `uv run blindcity compare`.
  levers.py    The eight levers. Single source of truth for ranges and defaults.
  rng.py       Seeded randomness. Determinism is a hard rule.
  config.py    Connection settings.
viewer/        Cosmetic city scene plus the lever panel — the human mode's control surface.
               No numbers, no charts, no trends.
infra/         Docker compose for the warehouse Postgres.
tests/         pytest.
docs/          See document map below.
```

Two naming notes, both deliberate:

- **`catalog/`, not `datahub/`.** A top-level `datahub` package would shadow the installed
  `acryl-datahub` module and break every import of the DataHub SDK.
- **`evaluation/`, not `eval/`.** Avoids a module named after a builtin. The *command* is still
  `uv run blindcity compare`.

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
uv run blindcity sim --seed 42 --years 20

# Metadata ingestion
uv run blindcity emit

# Agent, auto mode
uv run blindcity run --mode agent_datahub_live --out results/live.json

# Evaluation
uv run blindcity compare "results/*.json"
```

## Conventions

- **Python 3.11+, managed with `uv`.** The Analytics Agent requires 3.11 or newer.
- **Apache 2.0 headers stay intact.** No GPL code enters this repository. That rules out
  OpenTTD and Micropolis derivatives.
- **The simulation is deterministic.** Same seed produces the same city, always. The A/B evaluation
  is meaningless otherwise.
- **Lineage is generated and continuously validated.** The emitter never hand-writes an edge — it
  generates them from `blindcity.sim.causal.CAUSAL_EDGES`. That list is declared rather than
  extracted from the equations, so `causal_check.py` proves each edge by experiment and the test
  suite fails the build for any edge that cannot be demonstrated, or any edge with no experiment
  behind it. Adding an edge means adding its check.

## Dos and don'ts

- **Do set `TOOLS_IS_MUTATION_ENABLED=true`** in the MCP config. Mutation tools are not registered at
  all without it, so they never appear in the tool list.
- **Do keep the baseline honest.** The no-DataHub control gets the same model, prompt, seed, tool
  budget, and full SQL access. Only the metadata context differs.
- **Do spend effort on simulation fidelity, not on rendering.** The sim is the substrate the whole
  measurement rests on. The viewer is cosmetic: it should look like a city and carry the levers.
  Time spent making it pretty is time not spent on the thing being judged.
- **Do hold information parity across modes.** Every controller gets the same channel to the city's
  state; only the metadata differs. This is the experiment's control, not a preference.
- **Don't build a dashboard.** Any chart, trend line, gauge, or numeric readout of city state in the
  viewer breaks parity — it hands the human mode information the agent modes do not have and
  invalidates the comparison. Lever positions are the controller's own input and are exempt.
- **Don't ship only the upstream Analytics Agent.** Originality is a judged criterion; the closed
  loop is ours.
- **Do run `powershell -ExecutionPolicy Bypass -File infra/stack.ps1` before touching anything that needs Docker,** and again after any
  `datahub docker quickstart`. The engine on this host restarts often and quickstart resets the
  containers' restart policy. `docker ps` showing two containers instead of seven is the normal
  failure, not a crisis.
- **Don't trust a green test suite to mean a value is alive.** A constant passes every range check.
  This project has shipped four columns pinned at a bound, each one through a fully green suite.
  Require values to *move*, compare modes component by component, and check the fraction of rows
  sitting at the ceiling rather than the mean. The opening section of `docs/ERRORS.md` is the
  full version of this, and it is the single most useful thing in the documentation.
