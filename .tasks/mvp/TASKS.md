# MVP — hackathon submission

**Objective.** Ship a working Blind City entry by 2026-08-10, 5:00pm EDT.

**Status.** Updated 2026-08-01. Foundations complete. No application code written yet.

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

**How the work is organised.** Vertical slices, not days. Each slice is a coherent piece of the
product that can be finished and verified on its own. They are ordered by dependency: later slices
need earlier ones. Nothing about the ordering is a schedule — the deadline is the schedule, and the
cut line below is how you respond to running short.

**What the skeleton does and does not give you.** The package layout, the four commands, the eight
levers, the seeded RNG, and the warehouse container are real and tested. Deliberately absent: the
warehouse schema, the tick loop, any lineage code, and the viewer's framework — all of those are
design decisions that should be made by whoever makes them, not inherited from a stub. The lever
bounds in `blindcity/levers.py` are plausible placeholders, not calibrated numbers.

**Next action:** Slice 1, the simulation core. Everything it needs is running.

## Bootstrap

1. [x] Copy or clone this directory.
2. [x] Confirm 16 GB RAM, 25 GB free disk, Docker installed. — 63 GB RAM, 531 GB free,
   Docker 29.2.1.
3. [x] Install `uv` and Python 3.11+. — `uv` 0.11.32; `acryl-datahub` 1.6.0.17 installed as a uv
   tool pinned to Python 3.11. System Python is 3.14, too new for the DataHub dependency set;
   pin the project to 3.11.
4. [x] Run `datahub docker quickstart`. Confirm `localhost:9002` loads and
   `localhost:8080/api/graphql` answers unauthenticated. — both confirmed.
5. [x] Register on Devpost: https://datahub.devpost.com/register
6. [x] Join the DataHub Slack, channel `#agent-hackathon`, for live help from DataHub staff.

## Slices

### Slice 0 — Foundations

**Done.**

- [x] DataHub Core running and reachable. Quickstart plan `v1.5.0.6`. `localhost:9002` returns 200;
      `localhost:8080/api/graphql` answers unauthenticated as `__datahub_system` with no token.
      Note: the current quickstart profile is six containers, not fourteen, and DataHub's own
      metadata store is MySQL on `:3306` — our warehouse Postgres has its own container on 5432.
- [x] Warehouse Postgres running. PostgreSQL 16.14 in `blindcity-postgres` on 5432, healthy.
      Definition in `infra/postgres/docker-compose.yml`.
- [x] Repository scaffolded, Apache 2.0 `LICENSE` file added. uv project on Python 3.11, src layout,
      four CLI entry points wired, 9 tests passing, ruff clean.
- [x] Postgres confirmed as a supported Analytics Agent warehouse. The upstream README lists
      PostgreSQL among its queryable sources alongside Snowflake, BigQuery, MySQL, and
      SQLAlchemy-compatible databases generally. The old contradiction came from Postgres serving
      *both* roles — the Analytics Agent's own quickstart also uses Postgres for its persistence.
      Both roles are real; they are separate databases. **Still confirm hands-on during Slice 4**,
      when the Analytics Agent is actually wired up. It is no longer architecture-blocking: our own
      auto-mode agent reaches Postgres through SQLAlchemy, which is our code.

### Slice 1 — Simulation core

The tick loop and the economy. Nothing else can be verified until rows exist.

- [ ] Deterministic tick loop, seeded. Two runs on one seed must be identical.
- [ ] Citizens, households, jobs, income, satisfaction.
- [ ] Municipal budget with revenue and expenditure lines.
- [ ] Warehouse schema designed and created.
- [ ] Writes rows to Postgres.

**Verified when:** `uv run sim --seed 42 --years 20` completes twice with byte-identical output, and
the row counts in Postgres are in the millions.

### Slice 2 — City systems and levers

The domains the vision names, and the player's control surface wired into the model.

- [ ] Roads with traffic and wear.
- [ ] Power grid with demand, contracts, tariffs.
- [ ] Water and sewer capacity and load.
- [ ] Migration responding to conditions.
- [ ] All eight levers actually affecting the simulation.

**Verified when:** moving each lever produces a measurable, directionally sensible change in the
data. A lever nothing responds to is a bug, not a feature.

### Slice 3 — Metadata layer

The thesis of the entry. Do not cut.

- [ ] Postgres schemas ingested into DataHub.
- [ ] Glossary terms for every city concept.
- [ ] Lineage generated from the simulation's equations, emitted table and column level.
- [ ] Assertions on ranges and volumes.
- [ ] The stripped baseline catalog for the evaluation control: schemas only, realistic table names,
      no descriptions, no glossary, no lineage. `uv run datahub-emit --baseline`.

**Verified when:** the lineage graph is traversable in the DataHub UI and traces tax rate through to
revenue, and the graph was generated from the simulation rather than hand-authored.

### Slice 4 — Control surface and manual mode

- [ ] FastAPI: `GET /state`, `POST /lever`, `POST /advance`.
- [ ] Analytics Agent connected to Postgres and DataHub. Blocked on H1, the LLM API key.
- [ ] Confirm hands-on that the Analytics Agent issues SQL against our warehouse.
- [ ] Manual loop demonstrated end to end: ask, read, pull, observe.

### Slice 5 — Auto mode

The original contribution. Do not cut.

- [ ] Agent loop: read state, DataHub MCP for context, SQL, decide, actuate, advance.
- [ ] `TOOLS_IS_MUTATION_ENABLED=true` set so mutation tools register.
- [ ] The `--context none` control arm: same everything, DataHub context removed.
- [ ] Agent writes findings back into the catalog.

### Slice 6 — Viewer

- [ ] Canvas tile map and lever panel. No charts, no counters, no trends.

### Slice 7 — Evaluation harness

**Build the harness. Do not run the evaluation — that is H3.**

The runs cost real money and real time, and the results are the number the submission is built
around. Whoever runs them decides how many seeds and when.

- [ ] `uv run eval --seeds N` implemented: same agent, same seed, both context arms.
- [ ] Outcome metrics captured — population, solvency, citizen satisfaction after twenty simulated
      years.
- [ ] Results written somewhere durable and comparable across runs.
- [ ] Harness verified without spending a real evaluation: dry run or mocked agent.
- [ ] Hand off H3 with the exact command, the expected cost, and the expected wall-clock time.

### Slice 8 — Submission materials

Everything a judge reads, minus the parts a human owns.

- [ ] Project description written.
- [ ] README polished for a first-time reader who is not us.
- [ ] Sample outputs collected and attached.
- [ ] A dry-run check that the repository is complete and clones clean.

## Cut line

Decided in advance, so it is not decided in panic. Sacrifice in this order:

1. **Water and sewer.** Power and roads carry the same story.
2. **Viewer polish.** A crude map still communicates the premise.
3. **Agent write-back to the catalog.** A bonus, not the thesis.
4. **Multiple evaluation seeds.** One seed with an honest caveat beats none.

Never cut: generated lineage, the A/B evaluation, the three-minute video. Those are the submission.

## Open questions

- How realistically bad should the baseline's table names be? Realistic enough to be fair, documented
  plainly in the README so it does not read as rigged.
- Row volume target. A few thousand citizens on monthly ticks across twenty years should reach
  millions of rows honestly. Confirm once the schema exists.

## Human tasks

Not agent work. Either an agent cannot do them, or it should not. An agent that hits one of these
stops, says so, and continues with whatever else is unblocked — it does not improvise around them.

- [ ] **H1 — Provide an LLM API key.** Blocks Slice 4 and Slice 5, which is most of the remaining
      product. Set it up before starting a long unattended run. The Analytics Agent takes
      `LLM_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`; `openai`, `google`, `bedrock`, and
      `openai-compatible` are also supported. Never commit the key. Never ask an agent to create one.
- [ ] **H2 — Make the repository public.** Hard submission requirement, alongside Apache 2.0.
      Currently private. Outward-facing and effectively irreversible, so it stays a human decision.
      `gh repo edit sp-entertainment/contest-datahub-city-sim --visibility public`
- [ ] **H3 — Run the A/B evaluation.** Costs real tokens and real time, and produces the number the
      submission is built around. Slice 7 hands over a working harness and a cost estimate; the
      number of seeds and when to spend is a human call.
- [ ] **H4 — Record the demo video.** Under three minutes. On the never-cut list.
- [ ] **H5 — Submit on Devpost.** Before 2026-08-10, 5:00pm EDT.
- [ ] **H6 — Decide any scope cuts.** The cut line exists so this is not decided in panic, but
      applying it is a human call. An agent that is behind says so and proposes; it does not quietly
      drop work.

## Notes

- There is no hosted DataHub sandbox for the hackathon. Confirmed by DataHub staff.
- Auth stays off. Unauthenticated writes to `localhost:8080/api/graphql` work with nothing to
  configure.
- Bonus scoring for upstream contributions to DataHub. If a connector, skill, or documentation fix
  falls out of this work naturally, submit it.
