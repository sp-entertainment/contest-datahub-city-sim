# Handoff — superseded

> **Superseded 2026-08-01.** This was a one-time snapshot written to cross a machine boundary. The
> move happened and the bootstrap it describes is done. Current state lives in `TASKS.md`; the
> running environment is documented in `docs/ENVIRONMENT.md`. Kept for background only.
>
> Known stale in here: the fourteen-container quickstart figure (it is six), the environment section
> (the target machine has 63 GB), and "Where to pick up" step 1 (done and verified).

**Written.** 2026-08-01, at the end of the design session.

**Why.** Development is moving to a machine with more memory. The originating session cannot be
transferred, so everything it established is recorded here.

**State.** Design settled. No application code written. Repository contains documentation only.

## Read these first, in order

1. `AGENTS.md` — the vision statement, immutable, plus constraints and conventions.
2. `docs/DECISIONS.md` — seven decisions with full rationale. Do not relitigate these without cause;
   each one cost real investigation.
3. `.tasks/mvp/TASKS.md` — bootstrap steps and the day-by-day plan.
4. `docs/ERRORS.md` — two configuration traps recorded before they were hit.

This document covers only what those do not.

## What the project is, in one paragraph

A city simulation with no interface. It writes enormous volumes of data to Postgres. The player sees
the city and eight levers, and nothing else — no charts, no counters, no trends. To learn what is
happening, the player asks an agent, which reads DataHub to discover what data exists and what it
means, then queries Postgres and answers. The catalog plus the agent replace the game UI. Because we
wrote the simulation, we have ground truth, so the same agent can be run twice on one seed — with and
without DataHub context — to measure whether metadata actually improves decisions.

## Why the original plan changed

The session opened with a plan to fork OpenTTD. Three findings killed it, all recorded in
`docs/DECISIONS.md`: the Apache 2.0 submission requirement is incompatible with OpenTTD's GPLv2 and
Micropolis's GPLv3; OpenTTD is a transport tycoon with no taxes, utilities, or individual citizens;
and nine days does not accommodate archaeology on unfamiliar C++.

The session also opened with a misunderstanding of DataHub — that it stores and queries your data. It
does not. It is a metadata catalog: schemas, glossary, lineage, ownership, assertions, query history.
Its MCP server never touches data values. The agent reads DataHub for context and queries Postgres
for numbers. The vision survives this correction intact.

## Research findings worth not rediscovering

- **No hosted sandbox exists for the hackathon.** Confirmed by DataHub staff (Lakshay Nasa) in the
  `#agent-hackathon` Slack channel.
- **The DataHub Cloud 21-day trial has no self-serve signup.** Every call to action on
  `datahub.com/free-trial/` and `datahub.com/google-cloud-free-trial/` routes to the sales demo form.
  Not viable on a nine-day path. Do not chase it.
- **DataHub Lite is unusable here.** It does not support graph traversal of relationships, meaning no
  lineage. Lineage is the entire thesis.
- **Local OSS quickstart is unauthenticated by default.** Writes to `localhost:8080/api/graphql` work
  with no token and nothing to configure. Full write-back including tags is supported.
- **The Analytics Agent is open source, Apache 2.0**, and works against self-hosted DataHub Core.
  Cloud is optional. Claude is its default LLM. It has a REST API with SSE streaming alongside the web
  UI on `:8100`.

## Reference links

- Hackathon: https://datahub.devpost.com/ — resources page: https://datahub.devpost.com/resources
- Slack invite:
  https://join.slack.com/t/datahubspace/shared_invite/zt-3rxzw3uww-7F2k5mDpjKXIGLskiQPwLQ
  then join `#agent-hackathon`
- MCP server: https://github.com/acryldata/mcp-server-datahub
- Analytics Agent: https://github.com/datahub-project/analytics-agent
- Agent Context Kit: https://docs.datahub.com/docs/dev-guides/agent-context/agent-context
- DataHub Skills: https://docs.datahub.com/docs/dev-guides/agent-context/skills
- Quickstart: https://docs.datahub.com/docs/quickstart
- Free sample datapacks: `showcase-ecommerce` (1,049 entities), `bootstrap`, `nyc-taxi`, `healthcare`,
  `fiction-retail`

## Environment

The originating machine had 8 GB RAM and no Docker, which is why development moved. Quickstart needs
8 GB for itself plus 2 GB swap and 13 GB disk across 14 containers, so the target machine wants 16 GB
or more and roughly 25 GB free.

## Where to pick up

Day 1 of `.tasks/mvp/TASKS.md`. In practice:

1. Bring up `datahub docker quickstart`, confirm `localhost:9002` and unauthenticated GraphQL.
2. **Settle the Postgres question.** DataHub's own documentation contradicts itself on whether the
   Analytics Agent treats Postgres as a queryable warehouse or only as its own conversation store.
   The repository README says warehouse; one docs page implies otherwise. This gates the architecture
   — resolve it empirically before building further. If Postgres will not serve as the warehouse,
   DuckDB is the fallback, at the cost of weaker automated catalog ingestion.
3. Then the simulation, which depends on none of the above and can start in parallel.

## Open questions

- Row volume target. A few thousand citizens on monthly ticks across twenty years should reach
  millions of rows honestly. Confirm once the schema exists.
- How realistically bad to make the baseline's table names. Realistic enough to be fair, documented
  plainly in the README so it does not read as rigged.
- Whether any upstream contribution to DataHub falls out of this work naturally. Judges award bonus
  credit for connectors, skills, RFCs, or documentation fixes.

## Standing warnings

- **The deadline is 2026-08-10, 5:00pm EDT.** It will not move.
- **The cut line in `TASKS.md` was decided deliberately, while calm.** Honour it rather than
  improvising under pressure.
- **Verify the GitHub repository is public** before submitting. Apache 2.0 and a public repository are
  both hard requirements.
- **Do not ship only the upstream Analytics Agent.** Originality is judged. The closed loop in auto
  mode is the original contribution.
