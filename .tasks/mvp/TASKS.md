# MVP — hackathon submission

**Objective.** Ship a working Blind City entry by 2026-08-10, 5:00pm EDT.

**Status.** Design settled. No code written. Development moving to a higher-memory machine.

## Bootstrap on the new machine

1. Copy or clone this directory.
2. Confirm 16 GB RAM, 25 GB free disk, Docker installed.
3. Install `uv` and Python 3.11+.
4. Run `datahub docker quickstart`. Confirm `localhost:9002` loads and
   `localhost:8080/api/graphql` answers unauthenticated.
5. Register on Devpost if not already: https://datahub.devpost.com/register
6. Join the DataHub Slack, channel `#agent-hackathon`, for live help from DataHub staff.

Read `AGENTS.md` and `docs/DECISIONS.md` first. Everything already settled is recorded there.

## Plan

### Day 1 — Foundations

- [ ] DataHub Core running and reachable.
- [ ] Postgres running. **Verify it works as an Analytics Agent warehouse**, not only as its
      conversation store. Documentation is contradictory on this point; settle it before building on
      it.
- [ ] Repository scaffolded, Apache 2.0 `LICENSE` file added.

### Day 2 — Simulation core

- [ ] Deterministic tick loop, seeded.
- [ ] Citizens, households, jobs, income, satisfaction.
- [ ] Municipal budget with revenue and expenditure lines.
- [ ] Writes rows to Postgres.

### Day 3 — Simulation breadth

- [ ] Roads with traffic and wear.
- [ ] Power grid with demand, contracts, tariffs.
- [ ] Water and sewer capacity and load.
- [ ] Migration responding to conditions.
- [ ] Eight levers wired into the model.

### Day 4 — Metadata layer

- [ ] Postgres schemas ingested into DataHub.
- [ ] Glossary terms for every city concept.
- [ ] Lineage generated from the simulation's equations, emitted table and column level.
- [ ] Assertions on ranges and volumes.

### Day 5 — Control surface and manual mode

- [ ] FastAPI: `GET /state`, `POST /lever`, `POST /advance`.
- [ ] Analytics Agent connected to Postgres and DataHub.
- [ ] Manual loop demonstrated end to end: ask, read, pull, observe.

### Day 6 — Auto mode

- [ ] Agent loop: read state, DataHub MCP for context, SQL, decide, actuate, advance.
- [ ] `TOOLS_IS_MUTATION_ENABLED=true` set so mutation tools register.
- [ ] Agent writes findings back into the catalog.

### Day 7 — Viewer and evaluation

- [ ] Canvas tile map and lever panel. No charts, no counters.
- [ ] A/B harness: same agent, same seed, with and without DataHub context.
- [ ] Results across several seeds.

### Day 8 — Submission

- [ ] Demo video, under three minutes.
- [ ] Project description and README polish.
- [ ] Sample outputs attached.

### Day 9 — Reserve

Buffer. Something will overrun.

## Cut line

Decided in advance, so it is not decided in panic. Sacrifice in this order:

1. **Water and sewer.** Power and roads carry the same story.
2. **Viewer polish.** A crude map still communicates the premise.
3. **Agent write-back to the catalog.** A bonus, not the thesis.
4. **Multiple evaluation seeds.** One seed with an honest caveat beats none.

Never cut: generated lineage, the A/B evaluation, the three-minute video. Those are the submission.

## Open questions

- Does the Analytics Agent query Postgres as a warehouse cleanly? Day 1 gate.
- How realistically bad should the baseline's table names be? Realistic enough to be fair, documented
  plainly in the README so it does not read as rigged.
- Row volume target. A few thousand citizens on monthly ticks across twenty years should reach
  millions of rows honestly. Confirm once the schema exists.

## Notes

- There is no hosted DataHub sandbox for the hackathon. Confirmed by DataHub staff.
- Auth stays off. Unauthenticated writes to `localhost:8080/api/graphql` work with nothing to
  configure.
- Bonus scoring for upstream contributions to DataHub. If a connector, skill, or documentation fix
  falls out of this work naturally, submit it.
