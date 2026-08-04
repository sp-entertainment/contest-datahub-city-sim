# Handoff

**The entry point for anyone picking this up.** Read this first, then follow it.

**Last updated.** 2026-08-01, after the foundations were in place.

## How this file relates to TASKS.md

This file holds what does not change: orientation, hard rules, research findings, and the things
only a human can do. `TASKS.md` holds what does change: the checkboxes and the day-by-day plan.

**When they disagree, `TASKS.md` wins on status.** Do not copy progress into this file — that is the
drift that made the previous version of this document dangerous.

## What the project is

**A benchmark for whether catalog metadata improves agent decisions.** Not a game. A scenario puts
the city into a defined crisis; a controller pulls levers over a fixed turn budget; a composite
health index scores whether the city got back into the green in time. Three controllers face the
identical seed, crisis, and budget: a `human` (with the city render, the levers, and the Analytics
Agent to ask questions), `agent_datahub` (our agent with DataHub over MCP plus SQL), and
`agent_raw` (the same agent with SQL only). `agent_datahub` vs `agent_raw` measures the metadata;
`human` vs `agent_datahub` measures the automation.

The simulation is the substrate, and its fidelity is what makes the results mean anything — that is
where effort belongs. The viewer is cosmetic. Recorded 2026-08-02 in `docs/DECISIONS.md`.

Later sections of this file, and the original premise below, still describe the city and the
catalog accurately. The framing above is what the work is measured against.

## The original premise, in one paragraph

A city simulation with no interface. It writes enormous volumes of data to Postgres. The player sees
the city and eight levers, and nothing else — no charts, no counters, no trends. To learn what is
happening, the player asks an agent, which reads DataHub to discover what data exists and what it
means, then queries Postgres and answers. The catalog plus the agent replace the game UI. Because we
wrote the simulation, we have ground truth, so the same agent can be run twice on one seed — with and
without DataHub context — to measure whether metadata actually improves decisions.

## Before anything else: bring the stack up

```powershell
powershell -ExecutionPolicy Bypass -File infra/stack.ps1
```

Starts Docker Desktop if needed, brings the seven containers up in dependency order, waits on
health, and verifies that GMS GraphQL and warehouse SQL actually answer. Idempotent — run it any
time. `-Status` reports without changing anything.

Do not skip this and do not assume the stack is up because it was up an hour ago. The Docker engine
on this host restarts often, and until 2026-08-03 the DataHub containers were configured never to
come back afterwards. `docker ps` showing two containers instead of seven is the normal failure.
**If you ever run `datahub docker quickstart`, run `infra/stack.ps1` again after it** — quickstart
recreates its containers and resets their restart policy.

## Read these first, in order

1. `AGENTS.md` — the vision statement, immutable, plus constraints and conventions.
2. `docs/DECISIONS.md` — eight decisions with full rationale. Do not relitigate these without cause;
   each one cost real investigation.
3. `.tasks/mvp/TASKS.md` — current status and the day-by-day plan. The `Start here` section at the
   top tells you where each kind of learning gets written down.
4. `docs/ENVIRONMENT.md` — what is running, how to reach it, and every verified command.
5. `docs/ERRORS.md` — traps already hit, so they are not rediscovered. **Read this one properly
   rather than skimming it.** Several entries describe defects that passed a full green test suite,
   and the section on saturated columns describes a mistake this project has now made four times.

## Where things stand

Foundations are complete. Details and checkboxes live in `TASKS.md`; the short version:

- DataHub Core is up. `localhost:9002`, GraphQL on `localhost:8080/api/graphql`, unauthenticated.
- Warehouse Postgres 16 is up on `5432`, container `blindcity-postgres`.
- The Python project is scaffolded. uv, Python 3.11, src layout, four CLI entry points that parse
  their flags and exit 1 pointing at the slice that implements them. Nine tests pass, ruff clean.
- **No simulation code exists.** Slice 1 onward is unstarted.

## How the work is organised

Vertical slices, not days — see `TASKS.md`. Each slice is a coherent piece of the product that can be
finished and verified on its own, and they are ordered by dependency. The deadline is the schedule.

Work through them in order. **Your first task is Slice 1, the simulation core.** Everything it needs
is already running, and it depends on no external service and no credential.

Slices 4 and 5 need an LLM API key, which is a human task (H1 in `TASKS.md`). If it is not there when
you arrive, say so and keep going with what is unblocked — Slice 5 (the benchmark itself) and Slice
7 (the viewer) need no key.

## Postgres is settled

Do not relitigate it. The warehouse is Postgres, and the simulation writes to it.

Earlier notes in this repository treated "will the Analytics Agent query Postgres as a warehouse?" as
a blocking architectural gate, because DataHub's documentation appeared to contradict itself. It does
not: the Analytics Agent's README lists PostgreSQL among its queryable sources, alongside Snowflake,
BigQuery, MySQL, and SQLAlchemy-compatible databases generally. The confusion came from Postgres
playing two unrelated roles — the Analytics Agent's own quickstart also uses a Postgres instance for
its persistence. Both are real, and they are separate databases.

Still confirm hands-on during Slice 4, when the Analytics Agent is actually wired up. But it is not
blocking, and it does not gate the simulation: auto mode reaches Postgres through SQLAlchemy, which
is our own code.

## Hard rules

Violating any of these is expensive and often silent.

- **Determinism.** The simulation must reproduce exactly from a seed. Use `blindcity.rng`, never the
  global `random` module, and never iterate an unordered collection where order affects a draw. The
  A/B evaluation is meaningless otherwise.
- **No GPL code.** Apache 2.0 is a submission requirement. This is why OpenTTD and Micropolis were
  rejected.
- **Simulation fidelity is where effort goes; the viewer is cosmetic.** The sim is the substrate the
  measurement rests on. The scene needs to read as a city at a glance and nothing more. The lever
  panel is the exception — it is functional, because the `human` arm cannot play without it.
- **Information parity across arms is an experimental control.** Every controller gets the same
  channel to the city's state; only the metadata differs. No charts, counters, gauges, or numeric
  readouts of city state in the viewer — a number on screen hands the human arm information the
  agent arms lack and invalidates the comparison. Lever positions are the controller's own input
  and are exempt.
- **`agent_datahub` and `agent_raw` must differ in exactly one thing.** Same model, prompt, seed,
  turn budget, tool budget, and SQL access; only the catalog context differs. Any other difference
  invalidates the headline result.
- **The simulation is spatial.** Tiles, buildings on tiles, citizens with homes, workplaces, and
  positions. The viewer is downstream of this — without it there is nothing to draw.
- **Keep the baseline honest.** The no-DataHub control arm gets the same model, prompt, seed, tool
  budget, and full SQL access. Only the metadata context differs.
- **Do not ship only the upstream Analytics Agent.** Originality is judged. The closed loop in auto
  mode is the original contribution.
- **Work on `main`,** one concern per commit, and run `uv run pytest -q` before pushing.

## Stop and ask the human

`TASKS.md` has a **Human tasks** section at the end, H1 through H6: the API key, making the
repository public, running the A/B evaluation, the demo video, the Devpost submission, and any scope
cut. They are not agent work — either an agent cannot do them, or it should not.

Hitting one is not a reason to stop working. Say so plainly, then continue with whatever else is
unblocked. Do not improvise around them, and never create, enter, or commit a credential.

Two worth repeating because the failure is expensive:

- **Do not run the scored evaluation.** Build the harness in Slice 8, hand it over with a cost
  estimate.
  The runs spend real money and produce the number the whole submission rests on.
- **Do not quietly drop scope.** If you are behind, say so and propose a cut from the cut line.

## Research findings worth not rediscovering

- **No hosted sandbox exists for the hackathon.** Confirmed by DataHub staff (Lakshay Nasa) in the
  `#agent-hackathon` Slack channel.
- **The DataHub Cloud 21-day trial has no self-serve signup.** Every call to action on
  `datahub.com/free-trial/` and `datahub.com/google-cloud-free-trial/` routes to the sales demo form.
  Not viable on this timeline. Do not chase it.
- **DataHub Lite is unusable here.** It does not support graph traversal of relationships, meaning no
  lineage. Lineage is the entire thesis.
- **Local OSS quickstart is unauthenticated by default.** Writes to `localhost:8080/api/graphql` work
  with no token and nothing to configure. Full write-back including tags is supported.
- **The Analytics Agent is open source, Apache 2.0**, and works against self-hosted DataHub Core.
  Cloud is optional. Claude is its default LLM. It has a REST API with SSE streaming alongside the web
  UI on `:8100`.
- **DataHub's own metadata store is MySQL on 3306.** It is not the warehouse. Wiring the Analytics
  Agent to it by mistake is an easy and confusing failure.

## Reference links

- Hackathon: https://datahub.devpost.com/ — resources page: https://datahub.devpost.com/resources
- MCP server: https://github.com/acryldata/mcp-server-datahub
- Analytics Agent: https://github.com/datahub-project/analytics-agent
- Agent Context Kit: https://docs.datahub.com/docs/dev-guides/agent-context/agent-context
- DataHub Skills: https://docs.datahub.com/docs/dev-guides/agent-context/skills
- Quickstart: https://docs.datahub.com/docs/quickstart
- Free sample datapacks: `showcase-ecommerce` (1,049 entities), `bootstrap`, `nyc-taxi`, `healthcare`,
  `fiction-retail`

## Standing warnings

- **The deadline is 2026-08-10, 5:00pm EDT.** It will not move.
- **The repository is currently PRIVATE.** Apache 2.0 and a public repository are both hard
  submission requirements. Verify before submitting.
- **The cut line in `TASKS.md` was decided deliberately, while calm.** Honour it rather than
  improvising under pressure.
- **The lever bounds in `src/blindcity/levers.py` are uncalibrated placeholders.** Plausible, not
  tuned. Expect to revise them once the model runs.

## Open questions

- Row volume target. A few thousand citizens on monthly ticks across twenty years should reach
  millions of rows honestly. Confirm once the schema exists.
- How realistically bad to make the baseline's table names. Realistic enough to be fair, documented
  plainly in the README so it does not read as rigged.
- Whether any upstream contribution to DataHub falls out of this work naturally. Judges award bonus
  credit for connectors, skills, RFCs, or documentation fixes.

## Why the original plan changed

Recorded because it is the question a newcomer asks first. The session opened with a plan to fork
OpenTTD. Three findings killed it, all in `docs/DECISIONS.md`: the Apache 2.0 submission requirement
is incompatible with OpenTTD's GPLv2 and Micropolis's GPLv3; OpenTTD is a transport tycoon with no
taxes, utilities, or individual citizens; and the timeline does not accommodate archaeology on
unfamiliar C++.

The session also opened with a misunderstanding of DataHub — that it stores and queries your data. It
does not. It is a metadata catalog: schemas, glossary, lineage, ownership, assertions, query history.
Its MCP server never touches data values. The agent reads DataHub for context and queries Postgres
for numbers. The vision survives this correction intact.
