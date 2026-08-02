# MVP — hackathon submission

**Objective.** Ship a working Blind City entry by 2026-08-10, 5:00pm EDT.

**Status.** Updated 2026-08-02. Slices 1–3 built and reviewed; four items reopened by that review
(two in Slice 1, two in Slice 3) and marked unchecked below. Slice 4 has not started.
Slice 4+ not started.

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

**Next action:** clear the four reopened items in Slices 1 and 3, then Slice 4 — FastAPI control
surface and manual mode.

Slices 1–3 were built and reviewed on 2026-08-02. The review added per-edge lineage validation and
found a dead column: road congestion was pinned at 1.0 on every segment for the entire run, which
silently severed wear → congestion → commute time → satisfaction → migration (`docs/ERRORS.md`).

**A slice marked done is not therefore correct.** That bug passed the whole suite, because a test
asserting a value is within range is perfectly satisfied by a constant. When you check something
off, prefer a test that requires the value to *move* — the pattern in `tests/test_lever_effects.py`
and `blindcity.sim.causal_check`.

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

- [x] Deterministic tick loop, seeded. Two runs on one seed must be identical.
- [x] **A spatial city grid.** Tiles with terrain and zoning. The city occupies a map, not a
      spreadsheet — the viewer renders this, so it is a Slice 1 requirement, not a viewer concern.
- [x] Citizens and households, each **located**: a home tile, a workplace tile, and a position.
      Jobs, income, satisfaction.
- [x] Buildings with a type, a tile, and a visible condition (new, worn, derelict).
- [x] Municipal budget with revenue and expenditure lines.
- [x] Warehouse schema designed and created, carrying the spatial columns.
- [x] Writes rows to Postgres.
- [ ] **Guard determinism across processes.** Reopened 2026-08-02 in review. The current test runs
      both simulations in one interpreter, so it cannot catch a regression that depends on
      `PYTHONHASHSEED` — iteration over a set or a string-keyed dict that affects a draw. Shell out
      twice with different hash seeds and compare fingerprints. Cross-process identity was checked
      by hand once; nothing protects it going forward, and the A/B evaluation depends on it.
- [ ] **Re-record the warehouse numbers.** The `SEGMENT_CAPACITY` fix changed simulation behaviour,
      so the row counts and fingerprints below are stale. Re-run and update here and in
      `docs/ENVIRONMENT.md` once Docker is up.

**Verified when:** `uv run sim --seed 42 --years 20` completes twice with byte-identical output, the
row counts in Postgres are in the millions, and the city's state at any tick can be reconstructed
into a map — tiles, buildings, and where every citizen is.

**Verified 2026-08-02, now stale.** `uv run sim --seed 42 --years 20` → 2,118,197 rows in ~29s.
In-memory fingerprints identical for same seed. Tests: `tests/test_sim_determinism.py`. These
numbers predate the congestion fix — see the re-record item above.

### Slice 2 — City systems and levers

The domains the vision names, and the player's control surface wired into the model.

- [x] Roads as network segments on the grid, with traffic and wear.
- [x] Power grid with demand, contracts, tariffs — and which buildings are served.
- [x] Water and sewer capacity and load.
- [x] Migration responding to conditions: households arrive, occupy tiles, and leave.
- [x] Citizens commute along the road network between home and work.
- [x] All eight levers actually affecting the simulation.

**Verified when:** moving each lever produces a measurable, directionally sensible change in the
data. A lever nothing responds to is a bug, not a feature. Every system that the viewer must show —
wear, outages, congestion, abandonment — is queryable per tile.

**Verified 2026-08-02.** All eight levers change metrics directionally (`tests/test_lever_effects.py`).
Per-tile/segment fields: `tile_monthly` (condition, abandonment, power, water/sewer load),
`road_monthly` (traffic, wear, congestion), `building_monthly` (condition_band, power_served).

### Slice 3 — Metadata layer

The thesis of the entry. Do not cut.

- [x] Postgres schemas ingested into DataHub.
- [x] Glossary terms for every city concept.
- [x] Lineage generated from the causal graph, emitted table and column level.
- [x] **Every lineage edge validated against the running simulation.** Added 2026-08-02 in review:
      the edge list is declared, not extracted, so it needs proof. `blindcity.sim.causal_check`
      perturbs each source, runs the code that computes the target, and requires the target to
      move; `tests/test_causal_validation.py` fails the build on any edge that cannot be
      demonstrated or has no experiment. 29/29 currently pass.
- [x] Assertions on ranges and volumes.
- [x] The stripped baseline catalog for the evaluation control: schemas only, realistic table names,
      no descriptions, no glossary, no lineage. `uv run datahub-emit --baseline`.

**Verified when:** the lineage graph is traversable in the DataHub UI and traces tax rate through to
revenue, and every edge in it can be demonstrated against the simulation.

**Verified 2026-08-02.** Lineage generated from `blindcity.sim.causal.CAUSAL_EDGES`; the emitter
never hand-writes an edge. `uv run datahub-emit` / `--baseline` implemented. Tax→revenue edge proven
via `--dump-lineage`. All 29 edges pass validation. Live GMS emit requires DataHub containers up
(see ENVIRONMENT).

**Reopened 2026-08-02 in review — two items below are unchecked. Do them before Slice 4.**

- [ ] **Evaluate the assertions against Postgres.** They are currently declared and emitted as
      metadata, but nothing ever runs them, so an assertion in the catalog could simply be false —
      exactly the kind of stale metadata this entry argues against. Run each as SQL after a sim
      write and emit the pass/fail result alongside the assertion. A catalog that reports a failing
      assertion honestly is a better demo than one that only ever claims success.
- [ ] **Document the baseline naming in the README.** The control arm uses opaque names
      (`t_person_m`, `t_budg_m`) with no descriptions. That is realistic for a legacy warehouse, but
      undocumented it reads as rigging the A/B evaluation in our favour. State plainly what the
      control has and does not have, and why that is a fair representation of an uncatalogued
      warehouse. This is a fairness requirement, not polish — `AGENTS.md` calls for it and the
      evaluation's credibility rests on it.

### Slice 4 — Control surface and manual mode

- [ ] FastAPI: `GET /state`, `POST /lever`, `POST /advance`.
- [ ] `GET /scene` — everything the viewer draws for the current tick: tiles, buildings and their
      condition, road segments and their wear, utility coverage, and citizen positions. Shaped for
      rendering, not for analysis, and carrying no aggregates or derived statistics.
- [ ] Static file serving for the viewer, so the whole thing runs from one process.
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

The player's window onto the city, and the thing the demo video shows for three minutes. It must
read as a city, not as a debug view.

- [ ] Rendered city scene on a canvas: terrain, zoning, buildings, roads, utility infrastructure.
- [ ] Visible inhabitants moving between homes and workplaces along the roads.
- [ ] Condition shown visually, never numerically — worn roads look worn, unpowered buildings go
      dark, abandoned lots look derelict, congested roads look congested.
- [ ] Lever panel: the eight controls as real GUI inputs in manual mode, each showing its current
      position, each `POST`ing to `/lever`.
- [ ] Advance control, so the player can step the simulation and watch the consequence.
- [ ] No charts, counters, gauges, trend lines, or numeric readouts of city state.

**Verified when:** someone who has never seen the project can watch the city for thirty seconds,
say something true about how it is doing, and not be able to point at a single number on screen.

**Approach, decided** (`docs/DECISIONS.md`): plain HTML, 2D canvas, 2.5D isometric tiles, no build
step, served as static files by the FastAPI process. **Low fidelity is the target** — flat-shaded
isometric blocks and simple citizen sprites. It must read as a city sim at a glance; silhouette,
density, and condition carry that, not texture detail.

**Build the first version deliberately plain, then stop and move on.** `viewer/README.md` has the
concrete spec: extruded boxes where height is density, colour is type and shade is condition; dots
for citizens; full canvas redraw each tick; native HTML inputs for the levers. Roughly a day.
Sprite art, animation, day/night, camera controls, and building variety are explicitly out until
the submission is otherwise complete. If it looks flat and schematic, it is correct.

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
2. **Viewer polish** — *the polish, not the scene.* Revised 2026-08-01, when the viewer became a
   headline deliverable rather than a proof of concept. What is cuttable: animation smoothness,
   sprite variety, isometric depth, weather, day/night, decorative detail. What is **not**
   cuttable: a recognisable city, visible inhabitants, visible condition, and working lever inputs.
   Fall back to simpler tiles and static citizens before cutting the scene itself.
3. **Agent write-back to the catalog.** A bonus, not the thesis.
4. **Multiple evaluation seeds.** One seed with an honest caveat beats none.

Never cut: generated lineage, the A/B evaluation, a viewer that reads as a city, the three-minute
video. Those are the submission.

## Open questions

- ~~How realistically bad should the baseline's table names be?~~ Settled in DECISIONS 2026-08-02
  (`t_person_m`, `t_budg_m`, …).
- ~~Row volume target.~~ Settled: ~2.1M rows at seed 42 / 20 years (DECISIONS 2026-08-02).

## Human tasks

Not agent work. Either an agent cannot do them, or it should not. An agent that hits one of these
stops, says so, and continues with whatever else is unblocked — it does not improvise around them.

- [x] **H1 — Provide an LLM API key.** Done 2026-08-01, verified against the provider.
      **Google Gemini.** `LLM_PROVIDER=google` with `GOOGLE_API_KEY`, both in a local `.env` —
      copy `.env.example` and fill it in. `gemini-2.5-pro` and `gemini-2.5-flash` are both
      available on this key. The Analytics Agent also supports `anthropic`, `openai`, `bedrock`,
      and `openai-compatible` if we need to switch; that is a two-line change in `.env`.
      Never commit the key, never paste it into a prompt or an issue, and never ask an agent to
      create one. Agents read it from the environment and never handle its value.
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
