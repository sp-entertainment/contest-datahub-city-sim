# Agent Instructions — City Sim Agent Benchmark

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

**This is a benchmark for whether catalog metadata improves agent decisions.** It is not a
game, and the city is not the deliverable — it is the substrate that makes the measurement mean
something.

A **scenario** puts the city into a defined crisis. A **controller** pulls levers over a fixed turn
budget. A run is scored by a **composite health index**; "recovered" means the index crossed the
green threshold within the budget. Five controllers face the identical seed, crisis, and budget:

| Mode | Controller | Sees |
| --- | --- | --- |
| `human` | A person | The city render, the levers, and the Analytics Agent to ask questions |
| `agent_raw` | Our auto-mode agent | SQL only, no catalog context |
| `agent_datahub` | Our auto-mode agent | The same, plus DataHub descriptions, glossary, lineage |
| `agent_datahub_live` | Our auto-mode agent | The same, plus assertions read from DataHub each turn |
| `agent_analytics` | DataHub's Analytics Agent | It decides; it reads DataHub and the warehouse itself |

Three comparisons fall out: `agent_datahub` vs `agent_raw` measures descriptive metadata;
`agent_datahub_live` vs `agent_datahub` measures prescriptive metadata; `human` vs the agents
measures the automation.

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
  cli.py       The one entry point. Argument parsing only, no business logic.
  commands/    One handler per subcommand: sim, emit, run, compare. Lazy imports,
               so `--help` works with no database, no key and no Docker.
  sim/         Headless deterministic city simulation. Writes rows to Postgres.
               Also declares its causal graph, validated per edge (causal_check.py).
  catalog/     Metadata authoring and publication: schemas, glossary terms, lineage,
               assertions, and the operating guidance in operational.py.
  agent/       The agents and everything they read. Our own controller for the three
               SQL modes; advisor.py and advisor_controller.py for the mode that asks
               DataHub's Analytics Agent instead; guidance.py reads the bands back
               out of DataHub at run time.
  benchmark/   Scenario definition, health index, turn budget, controller interface,
               run harness, results. The measurement, and the point of the project.
  evaluation/  Folds run results into one comparison. `uv run blindcity compare`.
  levers.py    The eight levers. Single source of truth for ranges and defaults.
  rng.py       Seeded randomness. Determinism is a hard rule.
  config.py    Connection settings.
viewer/        Cosmetic city scene plus the lever panel. No numbers, no charts, no trends.
infra/         Docker compose for the warehouse Postgres, and the Analytics Agent setup.
tests/         pytest.
docs/          See document map below.
```

Two naming notes, both deliberate:

- **`catalog/`, not `datahub/`.** A top-level `datahub` package would shadow the installed
  `acryl-datahub` module and break every import of the DataHub SDK.
- **`evaluation/`, not `eval/`.** Avoids a module named after a builtin. The *command* is still
  `uv run blindcity compare`.

And one that is not: the distribution and CLI are still named `blindcity`, the project's working
title. Renaming a published entry point costs every reader with a command in their notes and buys
nothing the README does not already say.

`agent_analytics` runs the upstream DataHub Analytics Agent, patched only to support OpenAI
reasoning models — that patch is upstreamed, not vendored. The other three modes are our own agent
and are the original contribution.

### Runtime topology

Everything runs on one machine. DataHub Core via `datahub docker quickstart` (six containers as of
plan `v1.5.0.6`), Postgres as the warehouse in its own container on 5432, sim exposing a small
FastAPI control surface, Analytics Agent on `:8100`.

DataHub's own metadata store is MySQL on 3306 and is not the warehouse. See `docs/ENVIRONMENT.md`.

Auth stays off. DataHub OSS quickstart accepts unauthenticated writes to
`localhost:8080/api/graphql`, so no access token is needed.

## Document map

- `AGENTS.md` — this file. Vision, contest constraints, project map, conventions. `CLAUDE.md` is a
  symlink to it, so both names load the same document.
- `README.md` — what the project is, the result, and setup from a clean clone.
- `CONTRIBUTING.md` — project status, and the conventions a fork inherits.
- `docs/RESULTS.md` — the full mode comparison and method.
- `docs/FEATURES.md` — what the product does, feature by feature.
- `docs/ENVIRONMENT.md` — verified setup commands, running topology, credentials, lifecycle.
- `docs/DECISIONS.md` — append-only decision log with context and rationale.
- `docs/ERRORS.md` — problems hit and how they were resolved.
- `infra/analytics-agent/README.md` — standing up the upstream Analytics Agent for `agent_analytics`.

## Commands

Setup and verification commands, with observed results, are in `docs/ENVIRONMENT.md`.

```bash
# DataHub Core
datahub docker quickstart

# Simulation
uv run blindcity sim --seed 42 --years 20

# Metadata publication
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
- **Don't trust a green test suite to mean a value is alive.** A constant passes every range check,
  and a column pinned at a bound passes a bounds test by definition. Require values to *move*,
  compare modes component by component, and check the fraction of rows sitting at the ceiling
  rather than the mean. The opening section of `docs/ERRORS.md` works this through in full.
