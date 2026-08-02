# MVP — hackathon submission

**Objective.** Ship a working Blind City entry by 2026-08-10, 5:00pm EDT.

**Status.** Updated 2026-08-01. Bootstrap complete, DataHub Core verified running. No application
code written yet.

## Start here

This file is the live state of the work: read it, do the next unchecked thing, check it off, and
record what you learned in the document it belongs in.

**`HANDOFF.md` in this directory is the entry point.** It carries orientation, the hard rules, the
research findings, and the list of things only a human can do. It deliberately does not track
progress — this file does. When the two disagree about status, this file wins.

**Read first, in order:** `HANDOFF.md`, `AGENTS.md` (vision and constraints), `docs/DECISIONS.md`
(eight settled decisions — do not relitigate without cause), this file, `docs/ENVIRONMENT.md` (what
is running and how to reach it), `docs/ERRORS.md` (traps).

**Where each thing gets written down:**

| What you learned | Where it goes |
| --- | --- |
| A choice with alternatives and consequences | `docs/DECISIONS.md`, appended, never edited |
| A command that works, and what it produced | `docs/ENVIRONMENT.md` |
| Something that broke and how it was fixed | `docs/ERRORS.md` |
| Behaviour a player or judge can see | `docs/FEATURES.md` |
| Progress, and what is next | this file |

**What the skeleton does and does not give you.** The package layout, the four commands, the eight
levers, the seeded RNG, and the warehouse container are real and tested. Everything else is a
docstring saying which day builds it. Deliberately absent: the warehouse schema, the tick loop, any
lineage code, and the viewer's framework — all of those are design decisions that should be made
by whoever makes them, not inherited from a stub. The lever bounds in `blindcity/levers.py` are
plausible placeholders, not calibrated numbers.

**Next action:** Day 1, the Postgres warehouse gate. It is the last thing that can invalidate the
architecture, so it comes before any simulation code. Concretely: bring up Postgres in its own
container on 5432, install the Analytics Agent, point it at Postgres as a warehouse, and confirm it
actually issues queries against it. If it will not, DuckDB is the recorded fallback and that is a
`docs/DECISIONS.md` entry.

## Bootstrap on the new machine

1. [x] Copy or clone this directory.
2. [x] Confirm 16 GB RAM, 25 GB free disk, Docker installed. — 63 GB RAM, 531 GB free,
   Docker 29.2.1.
3. [x] Install `uv` and Python 3.11+. — `uv` 0.11.32; `acryl-datahub` 1.6.0.17 installed as a uv
   tool pinned to Python 3.11. System Python is 3.14, too new for the DataHub dependency set;
   pin the project to 3.11.
4. [x] Run `datahub docker quickstart`. Confirm `localhost:9002` loads and
   `localhost:8080/api/graphql` answers unauthenticated. — both confirmed, see Day 1.
5. [x] Register on Devpost: https://datahub.devpost.com/register
6. [x] Join the DataHub Slack, channel `#agent-hackathon`, for live help from DataHub staff.

Read `AGENTS.md` and `docs/DECISIONS.md` first. Everything already settled is recorded there.

## Plan

### Day 1 — Foundations

- [x] DataHub Core running and reachable. Quickstart plan `v1.5.0.6`. `localhost:9002` returns 200;
      `localhost:8080/api/graphql` answers unauthenticated as `__datahub_system` with no token.
      Note: the current quickstart profile is six containers, not fourteen, and DataHub's own
      metadata store is MySQL on `:3306` — our warehouse Postgres needs its own container on 5432.
- [x] Postgres running. PostgreSQL 16.14 in `blindcity-postgres` on 5432, healthy.
      Definition in `infra/postgres/docker-compose.yml`.
- [ ] **Verify Postgres works as an Analytics Agent warehouse**, not only as its conversation store.
      Documentation is contradictory on this point; settle it before building on it.
      **This is the gate. Nothing below it should start until it is answered.**
- [x] Repository scaffolded, Apache 2.0 `LICENSE` file added. uv project on Python 3.11, src layout,
      four CLI entry points wired, 9 tests passing, ruff clean.

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
