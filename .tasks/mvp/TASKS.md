# MVP — hackathon submission

**Objective.** Ship a working Blind City entry by 2026-08-10, 5:00pm EDT.

**Status.** Updated 2026-08-03. Slices 0–5 done and verified against live infrastructure. The
health index was rebuilt after a review found three components that did not measure what they
claimed, congestion was un-saturated, assertions were scoped to a `run_id`, and the warehouse was
re-recorded against a live Postgres. 102 tests, ruff clean.

**Next: Slice 6 — the agent modes.** Unstarted, and it is the entire result. Everything built so
far is apparatus for one number: whether `agent_datahub` recovers the city better than `agent_raw`.

Two Slice 4 items remain open, both needing a live Analytics Agent process rather than more code:
confirming hands-on that it issues SQL against our warehouse, and demonstrating the manual loop
end to end.

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

**What this project is.** A benchmark for whether catalog metadata improves agent decisions — not a
game. A scenario puts the city in a crisis; three controllers (`human`, `agent_datahub`,
`agent_raw`) pull levers over a fixed turn budget; a composite health index scores each run. The
simulation is the substrate and its fidelity is what makes results mean anything. The viewer is
cosmetic. See `AGENTS.md` and `docs/DECISIONS.md`, 2026-08-02.

**How the work is organised.** Vertical slices, not days. Each slice is a coherent piece of the
product that can be finished and verified on its own. They are ordered by dependency: later slices
need earlier ones. Nothing about the ordering is a schedule — the deadline is the schedule, and the
cut line below is how you respond to running short.

**What the skeleton does and does not give you.** The package layout, the four commands, the eight
levers, the seeded RNG, and the warehouse container are real and tested. Deliberately absent: the
warehouse schema, the tick loop, any lineage code, and the viewer's framework — all of those are
design decisions that should be made by whoever makes them, not inherited from a stub. The lever
bounds in `blindcity/levers.py` are plausible placeholders, not calibrated numbers.

**Next action:** Slice 6 — agent modes (`agent_datahub` / `agent_raw`) implementing the controller
interface from Slice 5.

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
   **Every session after the first: run `powershell -ExecutionPolicy Bypass -File infra/stack.ps1` instead.** Quickstart is for
   creating the containers; the script starts them in order and, unlike quickstart, leaves them
   configured to survive a Docker restart. See `docs/ERRORS.md`.
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
- [x] **Guard determinism across processes.** `tests/test_sim_determinism.py` shells out twice with
      `PYTHONHASHSEED=0` and `=1`, same seed/years, asserts identical fingerprints.
- [x] **Re-record the warehouse numbers.** Done 2026-08-03 against a live Postgres. 2,122,301 rows
      for one run, now recorded **per `run_id`** rather than whole-table, since the warehouse
      appends and the modes will write in parallel. `docs/ENVIRONMENT.md` also carries the column
      distributions and an `at ceiling` figure per column — re-check that table after any
      calibration change.

**Verified when:** `uv run sim --seed 42 --years 20` completes twice with byte-identical output, the
row counts in Postgres are in the millions, and the city's state at any tick can be reconstructed
into a map — tiles, buildings, and where every citizen is.

**Verified 2026-08-02.** In-memory fingerprints identical (including cross-process hash seeds).
Warehouse totals last measured 2,118,197 rows (pre-calibration; re-record pending Docker).

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

- [x] **Evaluate the assertions against Postgres.** `blindcity.catalog.assertions` runs each
      ASSERTIONS entry as SQL; `datahub-emit --evaluate-assertions` / `--evaluate-only` reports
      pass/fail and emit attaches results. Tests force fail cases so always-pass cannot hide.
- [x] **Document the baseline naming in the README.** Fairness section with `t_person_m` mapping
      and control-mode rationale.

### Slice 4 — Control surface and manual mode

- [x] FastAPI: `GET /state`, `POST /lever`, `POST /advance`. (`uv run sim --serve`)
- [x] `GET /scene` — tiles, buildings, roads, citizens; no health aggregates.
- [x] Static file serving for the viewer (`viewer/index.html` stub + mount).
- [x] Analytics Agent wiring documented (H1 key present). Full SSE demo still needs agent process
      + Docker; non-agent SQL path verified via sim writers and assertion evaluation.
- [ ] Confirm hands-on that the Analytics Agent issues SQL against our warehouse. (env documented;
      live agent process not run this session — Docker down.)
- [ ] Manual loop demonstrated end to end: ask, read, pull, observe. (needs live agent)

**Deferred 2026-08-09, deliberately.** Both remaining items are about the *upstream* DataHub
Analytics Agent, which exists here only as the tooling the `human` mode gets. Neither touches
`agent_datahub` vs `agent_raw`, which is the comparison the submission is built on. So they wait
until the agent modes reach the score we want; the human loop is the last thing wired up. The
specific risk when they are picked up is the one DECISIONS 2026-08-01 chased down: DataHub uses
Postgres for two unrelated things — a queryable warehouse and the Analytics Agent's own
conversation store — and DataHub's MySQL on 3306 is a third database in the mix. Pointing the
agent at the wrong one reads as working right up until the answers are nonsense, so the check is
"a query was observed hitting `blindcity` on 5432", not "the config is written down". If time runs
out, the cut line already covers this: ship the two-mode comparison and say so.

### Slice 5 — The benchmark: scenario, scoring, controllers

**New 2026-08-02. This is the product** — see `docs/DECISIONS.md`. Everything else is scaffolding
for it. Build it before the agent modes, because the modes implement its interface.

- [x] **Scenario definition.** `infrastructure_neglect` — 60 months neglect + shock, 36-turn budget.
- [x] **Composite health index**, weights 0.20/0.30/0.30/0.20, green **0.62**, in DECISIONS.
- [x] **Calibrate the lever bounds** — road/water max 8M; road repair formula fixed.
- [x] **Controller interface.** `Controller` protocol + scripted bad/good policies.
- [x] **Run harness.** `RunHarness` / `run_scenario` records per-turn index, components, levers.
- [x] **Run isolation in the warehouse.** Default append-by-`run_id`; `--reset-warehouse` opt-in.
- [x] **Results format** `RunResult` JSON (`scenario-bad.json` / `scenario-good.json` evidence).

**Verified when:** the same scenario run twice with the same controller and seed gives the same
score, a deliberately bad lever policy fails it, and a hand-played good policy recovers it.

**Verified 2026-08-02.** Bad policy: recovered=False, final≈0.417. Good policy: recovered=True,
green_turn=31, final≈0.653. Deterministic trajectories. 93 tests pass.

### Slice 6 — Agent modes

The original contribution. Do not cut.

**In progress. See `.tasks/mvp/SLICE6-HANDOFF.md` before continuing.**

- [x] Agent loop: read state, catalog for context, SQL, decide, actuate, advance.
      `uv run agent --mode agent_datahub|agent_raw`.
- [x] `agent_datahub` and `agent_raw` as two controllers over one implementation — identical model,
      prompt, tool budget, and SQL access, differing only in catalog context. **Any other difference
      between them is a bug that invalidates the headline result.** No branch on the mode exists in
      the loop; guarded by `tests/test_agent.py`.
- [x] Crisis history written to the warehouse, so the cause of the crisis is discoverable by SQL.
- [ ] Clean live smoke run for both modes, and the real per-mode cost of a 36-turn run for H3.
- [ ] Agent writes findings back into the catalog.
- [ ] `TOOLS_IS_MUTATION_ENABLED=true` — only applies if the MCP path is adopted; the catalog is
      currently read over GMS GraphQL. See the handoff for the reasoning and the seam.
- [x] **The warehouse is cleared before every agent run.** Added 2026-08-09. `--keep-warehouse`
      opts out; `--force-clean` overrides the guard that refuses to clear under a run still
      playing. A warehouse holding twenty previous cities changes planner choices, `ANALYZE` cost,
      and how much a mis-scoped query can see — none of which may differ between two modes that
      are meant to be identical. During development a clean slate is worth more than an archive.
- [ ] **Close the `public.*` search_path escape.** Scheduled for immediately after the clean
      comparison run, at the user's call — 2026-08-09. The agent's connection has `search_path`
      set to its per-run view schema with `public` left out, so unqualified `SELECT ... FROM
      road_monthly` is structurally scoped to one run. But `search_path` is a *resolution order,
      not a permission*: a model that writes `public.road_monthly` reads the pooled table across
      every run in the database and gets a confident number about a city that does not exist.
      Nothing fails; it lies. No observed query has done it, and both modes are equally exposed so
      it cannot bias the comparison — but "the model has not thought to type six extra characters"
      is not a correctness guarantee, and a model that reads `information_schema` (which it can,
      and which reports `public` as the real schema) and decides to be explicit walks straight
      through. **Fix:** a separate read-only role with `REVOKE ... ON SCHEMA public`, granted only
      on the run schema, so the view-creating connection and the reading connection hold different
      credentials. Clearing the warehouse each run shrinks the blast radius — one stale run rather
      than twenty — but does not close it, because both modes still write to `public`.

### Slice 7 — Viewer and the human mode

Cosmetic scene, functional controls. The scene is the first thing to cut under time pressure; the
lever panel is not, because the `human` mode cannot play without it.

- [ ] Lever panel: the eight controls as GUI inputs, each showing its position, each `POST`ing to
      `/lever`. **Functional — required for the human mode.**
- [ ] Advance control, so the player can step a turn and see the consequence.
- [ ] City scene on a canvas: isometric tiles, buildings as blocks, roads, citizens as dots.
      **Cosmetic — low fidelity by design.**
- [ ] Condition shown visually, never numerically — worn roads look worn, unpowered buildings go
      dark, derelict lots look derelict.
- [ ] No charts, counters, gauges, trend lines, or numeric readouts of city state. This is
      information parity between modes, not a style rule.
- [ ] The human mode wired to the Analytics Agent, so the player can ask questions and then act.

**Verified when:** a person can play a scenario end to end and get a score comparable to an agent
mode's, and cannot see a single number about the city's state that the agent modes do not also get.

**Approach, decided** (`docs/DECISIONS.md`): plain HTML, 2D canvas, 2.5D isometric tiles, no build
step, served as static files by the FastAPI process. `viewer/README.md` has the concrete spec:
extruded boxes where height is density, colour is type and shade is condition; dots for citizens;
full canvas redraw each turn; native HTML inputs for the levers. Roughly a day. Sprite art,
animation, day/night, and camera controls are out until the submission is otherwise complete. If it
looks flat and schematic, it is correct.

### Slice 8 — Run the comparison

**Build the harness. Do not run the scored evaluation — that is H3.**

Agent runs cost real money and real time, and produce the number the submission is built around.

- [ ] `uv run eval` drives all three modes through one scenario on one seed.
- [ ] Per-mode results captured: health trajectory, turn green was reached or not reached, lever
      history, component breakdown.
- [ ] Results comparable across seeds and across days.
- [ ] Verified without spending a real evaluation: dry run, mocked agent, or scripted controller.
- [ ] Hand off H3 with the exact command, the expected cost, and the expected wall-clock time.

### Slice 9 — Submission materials

Everything a judge reads, minus the parts a human owns.

- [ ] Project description written.
- [ ] README polished for a first-time reader who is not us.
- [ ] Sample outputs collected and attached.
- [ ] A dry-run check that the repository is complete and clones clean.

## Cut line

Decided in advance, so it is not decided in panic. Sacrifice in this order:

1. **The city scene.** Revised 2026-08-02, when the project was reframed as a benchmark. The render
   is cosmetic — cut it to bare coloured tiles, or to nothing, before cutting anything else. The
   **lever panel is not part of this cut**: without it the human mode cannot play.
2. **Water and sewer.** Power and roads carry the same story.
3. **The `human` mode.** Two agent modes still answer the metadata question, which is the headline.
   Losing the human mode costs the automation comparison, not the thesis.
4. **Agent write-back to the catalog.** A bonus, not the thesis.
5. **Multiple seeds.** One seed with an honest caveat beats none.

Never cut: generated and validated lineage, the `agent_datahub` vs `agent_raw` comparison, the
scenario and health index that make it scoreable, the three-minute video. Those are the submission.

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
