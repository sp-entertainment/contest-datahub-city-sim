# Handoff

**The entry point for anyone picking this up.** Read this first, then follow it.

**Last updated.** 2026-08-01, after Day 1 environment work.

## How this file relates to TASKS.md

This file holds what does not change: orientation, hard rules, research findings, and the things
only a human can do. `TASKS.md` holds what does change: the checkboxes and the day-by-day plan.

**When they disagree, `TASKS.md` wins on status.** Do not copy progress into this file — that is the
drift that made the previous version of this document dangerous.

## What the project is, in one paragraph

A city simulation with no interface. It writes enormous volumes of data to Postgres. The player sees
the city and eight levers, and nothing else — no charts, no counters, no trends. To learn what is
happening, the player asks an agent, which reads DataHub to discover what data exists and what it
means, then queries Postgres and answers. The catalog plus the agent replace the game UI. Because we
wrote the simulation, we have ground truth, so the same agent can be run twice on one seed — with and
without DataHub context — to measure whether metadata actually improves decisions.

## Read these first, in order

1. `AGENTS.md` — the vision statement, immutable, plus constraints and conventions.
2. `docs/DECISIONS.md` — eight decisions with full rationale. Do not relitigate these without cause;
   each one cost real investigation.
3. `.tasks/mvp/TASKS.md` — current status and the day-by-day plan. The `Start here` section at the
   top tells you where each kind of learning gets written down.
4. `docs/ENVIRONMENT.md` — what is running, how to reach it, and every verified command.
5. `docs/ERRORS.md` — traps already hit, so they are not rediscovered.

## Where things stand

Day 1 is complete except one blocking item. Details and checkboxes live in `TASKS.md`; the short
version:

- DataHub Core is up. `localhost:9002`, GraphQL on `localhost:8080/api/graphql`, unauthenticated.
- Warehouse Postgres 16 is up on `5432`, container `blindcity-postgres`.
- The Python project is scaffolded. uv, Python 3.11, src layout, four CLI entry points that parse
  their flags and exit 1 pointing at the day that implements them. Nine tests pass, ruff clean.
- **No simulation code exists.** Days 2 onward are unstarted.

## Your first task, and it blocks everything else

Determine empirically whether the DataHub Analytics Agent will query our Postgres **as a warehouse**,
or whether it only uses Postgres as its own conversation store. DataHub's own documentation
contradicts itself: the repository README lists Postgres as a supported warehouse, one docs page
implies otherwise.

Install the Analytics Agent, point it at
`postgresql://blindcity:blindcity@localhost:5432/blindcity`, and settle it by observing whether it
actually issues SQL against that database.

- **If yes.** Check the item off in `TASKS.md` and proceed to Day 2.
- **If no.** DuckDB is the recorded fallback. Write a `docs/DECISIONS.md` entry, then revise the
  plan — this weakens the Day 4 automated-ingestion items, and several later steps assume Postgres.
  Revising the plan is the work. Do not check the box and carry on as though nothing changed.

## Hard rules

Violating any of these is expensive and often silent.

- **Determinism.** The simulation must reproduce exactly from a seed. Use `blindcity.rng`, never the
  global `random` module, and never iterate an unordered collection where order affects a draw. The
  A/B evaluation is meaningless otherwise.
- **No GPL code.** Apache 2.0 is a submission requirement. This is why OpenTTD and Micropolis were
  rejected.
- **No instrumentation in the viewer.** No charts, counters, trend lines, or warning states. Showing
  the city is the point; showing statistics about it defeats the premise.
- **Keep the baseline honest.** The no-DataHub control arm gets the same model, prompt, seed, tool
  budget, and full SQL access. Only the metadata context differs.
- **Do not ship only the upstream Analytics Agent.** Originality is judged. The closed loop in auto
  mode is the original contribution.
- **Work on `main`,** one concern per commit, and run `uv run pytest -q` before pushing.

## Stop and ask the human

These cannot be done by an agent, or should not be done without a decision. Do not improvise around
them — surface them and continue with whatever else is unblocked.

- **API credentials.** The Analytics Agent and auto mode both need an LLM API key. Never enter,
  generate, or commit one. Ask.
- **Making the repository public.** Required for submission, but it is an outward-facing,
  effectively irreversible action. The human's call.
- **The demo video.** Under three minutes, and part of the submission. A human makes it.
- **Submitting on Devpost.** A human does this.
- **Cutting scope.** The cut line in `TASKS.md` was decided deliberately while calm. If you are
  behind, say so and propose the cut. Do not quietly drop things.
- **Spending real money.** Any evaluation run costs LLM tokens. Say what a run will cost before
  running many of them.

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
