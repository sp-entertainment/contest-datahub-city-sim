# Decisions

> Append-only. Never edit past entries.

## 2026-08-01 — Reject OpenTTD and Micropolis as the simulation base

**Context.** Original plan was to fork OpenTTD, add data generation, and modify its UI. Micropolis
was considered as the alternative with better domain fit.

**Options.** Fork OpenTTD; fork Micropolis; use OpenTTD unmodified through its admin port; write a
purpose-built simulation.

**Decision.** Write our own headless simulation in Python.

**Rationale.**
- **License conflict.** Submissions must be Apache 2.0. OpenTTD is GPLv2, Micropolis is GPLv3.
  A modified derivative of either cannot be relicensed.
- **Domain mismatch.** OpenTTD is a transport tycoon, not a city simulation. It has no taxes, no
  utilities, no individual citizens — precisely the domains the vision calls for.
- **Time.** Nine days. Archaeology on 500k lines of unfamiliar C++ is not affordable.
- **Judging weight on engine quality is zero.** The simulation is a data source.

**Consequences.** We lose game-quality visuals. Mitigated by a small canvas tile view. We gain full
control of the schema, which means full control of the lineage graph.

## 2026-08-01 — Correct the understanding of what DataHub is

**Context.** The vision assumed DataHub stores and queries the city's data directly.

**Decision.** Treat DataHub as the map, not the territory. It holds metadata only: schemas, glossary
terms, lineage, ownership, assertions, query history. The agent reads DataHub for context, then
queries Postgres for values.

**Rationale.** DataHub's MCP server never accesses data values. Any design assuming otherwise fails
on first contact.

**Consequences.** Two tools in the agent loop rather than one. The vision survives intact — DataHub
still replaces the UI's job of finding and explaining the relevant numbers.

## 2026-08-01 — Postgres as the warehouse

**Context.** The agent needs a real SQL store behind the metadata layer.

**Decision.** Postgres.

**Rationale.** DataHub ships a first-class Postgres ingestion connector, so schemas populate the
catalog automatically rather than being hand-waved. The Analytics Agent supports it via SQLAlchemy.

**Consequences.** One documentation page describes Postgres as the Analytics Agent's own conversation
store rather than a queryable warehouse, while the repository README lists it as a supported
warehouse. Verify empirically on day one before committing further.

## 2026-08-01 — Both manual and auto modes, split across two agents

**Context.** The vision wants a human pulling levers. The "Agents That Do Real Work" track rewards
autonomy. Judging also rewards originality beyond existing DataHub features.

**Decision.** Manual mode uses the upstream `datahub-analytics-agent` unmodified. Auto mode is a
closed-loop agent we build.

**Rationale.** Shipping only the upstream agent would mean contributing a data source, not an agent.
The split gets a polished question-answering surface for free while keeping the original work
clearly ours.

**Consequences.** Two agent surfaces to demo. Auto mode carries the originality score.

## 2026-08-01 — Lineage generated from the simulation, not hand-authored

**Context.** Lineage could be written by hand into DataHub, or derived from the simulation itself.

**Decision.** Generate it. The simulation's equations are the causal graph; emit it as a build
artifact.

**Rationale.** A city simulation has real causality — tax rate feeds disposable income, feeds
migration, feeds population, feeds revenue, feeds tax rate. Real data teams maintain lineage badly
and partially. A simulation knows its own causality exactly. This is the entry's distinguishing idea.

**Consequences.** Roughly half a day of design up front. The lineage graph stays correct for free as
the simulation changes.

## 2026-08-01 — A/B evaluation as the submission's spine

**Context.** Needed a way to show DataHub doing real work rather than decorating a demo.

**Decision.** Run auto mode twice on identical seeds — once with DataHub context, once with only
`information_schema` — and compare city outcomes over twenty simulated years.

**Rationale.** We wrote the simulation, so ground truth exists. No real data team can run this
experiment; their history only happened once.

**Consequences.** Costs roughly a day. Produces the one number the submission is built around.
The control must be documented as a control, with realistic table names and no descriptions, so it
does not read as rigged.

## 2026-08-01 — Run locally, unauthenticated; no hosted sandbox exists

**Context.** Investigated DataHub Cloud free trial as a way around local resource limits.

**Decision.** Run DataHub Core locally on a machine with sufficient memory.

**Rationale.** DataHub staff confirmed in the hackathon Slack that there is no hosted sandbox for
participants. The advertised 21-day Cloud trial has no self-serve signup; every call to action routes
to a sales demo form. Not viable on a nine-day critical path.

**Consequences.** Development moved to a higher-memory machine. Quickstart needs 8 GB for itself plus
2 GB swap and 13 GB disk, across 14 containers. Auth stays off, so no access token is needed.

## 2026-08-01 — Single `blindcity` package under `src/`, and the `catalog` rename

**Context.** The project map in `AGENTS.md` named five top-level directories, one of them `datahub/`.
Scaffolding the Python project forced the question of whether those are importable packages.

**Options.** Five top-level packages as mapped; one distribution with subpackages under `src/`.

**Decision.** One `blindcity` distribution, src layout, with `sim`, `catalog`, `agent`, and
`evaluation` as subpackages. `viewer/` and `infra/` stay top-level and are not Python.

**Rationale.**
- **`datahub/` as a top-level package is a landmine.** It shadows the installed `acryl-datahub`
  module, so `import datahub` inside our own code silently resolves to us instead of the SDK. Renamed
  to `catalog`.
- `eval` as a module name shadows a builtin. Renamed to `evaluation`; the command stays `uv run eval`.
- src layout means tests run against the installed package, so a packaging mistake fails locally
  rather than after the submission is cloned by a judge.

**Consequences.** The project map in `AGENTS.md` was updated to match, with both renames explained
inline so neither gets "corrected" back.

## 2026-08-01 — Close the Postgres warehouse question

**Context.** The earlier Postgres decision left an open worry: one DataHub docs page appeared to
describe Postgres as only the Analytics Agent's conversation store, contradicting the repository
README. It was recorded as a gate to settle before building further.

**Decision.** Postgres stands as the warehouse. The question is closed as an architectural gate and
demoted to a hands-on check when the Analytics Agent is wired up.

**Rationale.** The Analytics Agent README lists PostgreSQL among its queryable sources alongside
Snowflake, BigQuery, MySQL, and SQLAlchemy-compatible databases generally. The apparent contradiction
was Postgres playing two unrelated roles: the Analytics Agent's own quickstart also uses a Postgres
instance for persistence. Both are real and they are separate databases. Separately, the gate never
had the blocking weight first assigned to it — our auto-mode agent, which carries the originality of
the submission, reaches Postgres through SQLAlchemy in our own code and does not depend on the
upstream agent's connector support at all.

**Consequences.** The simulation can start immediately rather than waiting on an external
verification. DuckDB is no longer on the table. If the hands-on check in Slice 4 surprises us, it
costs manual mode, not the architecture.

## 2026-08-01 — Plan in vertical slices; humans own a named set of tasks

**Context.** The plan was laid out as nine numbered days. Work is now being handed to an agent
expected to run through it largely unattended.

**Decision.** Replace the day structure with dependency-ordered vertical slices, and collect
everything a human must do into a single `Human tasks` section, H1 through H6.

**Rationale.** Day numbers encode a schedule that was already wrong the moment the work started, and
they invite an agent to measure itself against a calendar rather than against working software. Each
slice instead names what "done" looks like. The human tasks were previously scattered as asides
inside the plan, which is exactly how an unattended agent ends up improvising around a missing API
key or spending real money on an evaluation run.

**Consequences.** `TASKS.md` is restructured and every "Day N" reference in the codebase and docs was
updated to point at a slice. The A/B evaluation is explicitly built-but-not-run by agents.

## 2026-08-02 — The project is an agent benchmark, not a game

**Context.** The entry had been shaped as a city simulation whose UI was replaced by a catalog and an
agent. That framing made the viewer a headline deliverable and left the A/B evaluation as the last
slice. The intent is the other way round: the evaluation *is* the product, and the city is the
substrate that makes it meaningful.

**Decision.** Blind City is a benchmark for whether catalog metadata improves agent decisions. A
**scenario** puts the city into a defined crisis. A **controller** pulls levers over a fixed turn
budget. A run is scored by a **composite health index**, and "recovered" means the index crossed a
green threshold within the budget. Three controllers face the identical seed, crisis, and budget:

| Arm | Controller | Sees |
| --- | --- | --- |
| `human` | A person | The city render, the levers, and the upstream Analytics Agent to ask questions |
| `agent_datahub` | Our auto-mode agent | DataHub over MCP, plus SQL against the warehouse |
| `agent_raw` | Our auto-mode agent | SQL against the warehouse only, no catalog context |

**Rationale.**
- **Simulation fidelity is what makes the result mean anything**, so effort belongs there. A crisis
  that is trivially recoverable, or unrecoverable regardless of skill, measures nothing.
- **Three arms separate two different questions.** `agent_datahub` vs `agent_raw` isolates the value
  of the metadata. `human` vs `agent_datahub` says whether the automation is worth having at all.
  Giving the human the Analytics Agent makes them a realistic operator-with-tooling baseline rather
  than a strawman.
- **A composite index gives one comparable number** with a component breakdown for the writeup, and
  a trajectory that plots well in a three-minute video.
- We wrote the simulation, so ground truth exists and the experiment is repeatable — which no real
  data team can do with their own history.

**Consequences.**
- **The viewer is demoted to cosmetic.** It does not need to represent the city faithfully. It needs
  to look like a city and carry the lever controls for the human arm. This reverses the 2026-08-01
  decision that made a recognisable city never-cut; the levers stay required because the human arm
  cannot exist without them, but scene fidelity is now the first thing to cut.
- **Information parity becomes an experimental control, not an aesthetic rule.** Every arm must get
  the same channel to the city's state; only the metadata differs. The existing "no charts, no
  counters" rule now has a stronger justification than the original one: a numeric readout in the
  viewer would hand the human arm an information channel the agent arms do not have, and invalidate
  the comparison.
- **Lever bounds stop being placeholders.** They determine whether a crisis is recoverable, so they
  need calibrating against an actual scenario.
- **Runs must be isolated in the warehouse.** Arms run in parallel and all write history; without a
  run identifier they overwrite each other. The schema needs a `run_id`, and the sim must stop
  truncating shared tables.
- New work that existed in no slice: scenario definition, health index and green threshold, turn
  budget, a controller interface the three arms implement, a run harness, and a results format.

**Future, explicitly not now.** Seeding the simulation from real historical city data, so the
benchmark runs against real conditions rather than generated ones. Recorded so it is not
rediscovered as a new idea; out of scope before the deadline.

## 2026-08-02 — Validate every lineage edge instead of claiming it was derived

**Context.** Review of Slice 3 found that `CAUSAL_EDGES` is a hand-written list. `systems.py` never
imports it — the only consumer is the emitter. So the lineage was declared beside the equations, not
derived from them, and could drift from them silently. `AGENTS.md` and the earlier decision entry
both claimed derivation. The existing test was circular: it asserted the graph was built from
`CAUSAL_EDGES`, which is true by construction and would pass if every edge were wrong.

**Options.** Reword the claim and accept hand-maintained lineage; make `systems.py` consume the edge
list so the equations and the graph are one structure; extract edges by instrumenting the simulation
at runtime; keep the declaration but require every edge to survive an experiment.

**Decision.** Keep the declaration and validate it. `blindcity.sim.causal_check` runs an experiment
per edge — perturb the source, run the code that computes the target, require the target to move in
the stated direction — and `tests/test_causal_validation.py` fails the build for any edge that
cannot be demonstrated, or any edge with no experiment behind it. All 29 edges pass.

**Rationale.**
- **It makes the claim true and checkable.** "Every lineage edge is continuously verified against
  the running simulation" is defensible, and stronger than what most production data platforms can
  say about their own lineage. Derivation-by-instrumentation would be the literal version, but it is
  invasive and the schedule does not have room.
- **It catches drift in the direction that matters.** An edge that stops being real fails the suite
  by name. An edge added without evidence fails too.
- **It found a real bug immediately** (below), which derivation would not have — a derived graph
  would have faithfully recorded a dependency that was numerically dead.
- The perturbation pattern already existed in `tests/test_lever_effects.py`; this extends it from 8
  levers to all 29 edges.

**Consequences.** Four pure helpers were extracted from the system functions —
`assign_power_service`, `compute_water_load`, `compute_congestion`, `compute_balance` — so an
injected source value is not overwritten before the target is computed. That refactor was verified
fingerprint-identical before any behavioural change was made. Adding a causal edge now means adding
its experiment; that is the cost, and it is the point. Wording in `AGENTS.md`, `causal.py`,
`catalog/__init__.py`, and `emit.py` was corrected to describe validation rather than derivation.

## 2026-08-02 — Size road capacity so congestion is an informative signal

**Context.** Validating the wear → congestion edge failed. Investigation showed congestion was
exactly 1.0 on all 458 road segments, for the entire run: per-segment traffic ran a median of ~89
against a wear-adjusted capacity of 16–40, so the clamp always fired.

**Decision.** Introduce `SEGMENT_CAPACITY = 150.0`, sized against observed traffic.

**Rationale.** A column that never varies is worse than a missing one — it is a dead input the agent
may reason over as though it means something, and it silently severed wear → congestion → commute
time → satisfaction → migration. The whole point of the entry is that an agent finds real structure
in this data.

**Consequences.** Mean congestion is now ~0.76 and moves with wear and population, so road
maintenance has a visible downstream effect. **Simulation behaviour changed**, so every recorded
fingerprint and row count from 2026-08-02 is stale and needs regenerating once Docker is back up;
`docs/ENVIRONMENT.md` is marked accordingly. Regression guarded by
`test_causal_validation.py::test_congestion_is_not_saturated`.

## 2026-08-01 — The viewer renders an actual city, and the simulation becomes spatial

**Context.** The viewer was scoped as a crude tile map — enough to communicate the premise, and
second on the cut line. The intent is stronger than that: it should look like a city simulation, with
the city, its infrastructure, and its inhabitants visible on screen, and the levers as GUI inputs.

**Decision.** The viewer renders a recognisable city scene with visible inhabitants and visibly
degrading infrastructure. To make that possible, **the simulation gains a spatial model**: a tile
grid, buildings placed on tiles, and citizens with home tiles, workplace tiles, and positions.
Rendering is plain HTML and a 2D canvas drawing 2.5D isometric tiles — no framework, no build step,
served as static files by the sim's FastAPI process. Low fidelity is the target: flat-shaded blocks
and simple sprites.

**Rationale.**
- **The premise reads better, not worse.** Removing the UI only means something if there is a city
  there to look at. A crude map makes the entry look unfinished; a city makes the absence of charts
  look deliberate.
- **It is what the demo video shows.** Three minutes of judged material is mostly this screen.
- **Space was the missing prerequisite.** Citizens had jobs and income but no location, so there was
  literally nothing to draw. This is the substantive change — the viewer is downstream of it.
- **No framework and no build step** keeps the repo clone-and-run for a judge, and keeps a day of
  toolchain work out of a nine-day schedule. Isometric tiles read as a city for far less effort
  than 3D.

**Consequences.** Slice 1 grows a spatial grid and located citizens; Slice 2 puts roads, utilities,
and commuting on that grid; Slice 4 adds `GET /scene` and static file serving. The schema carries
spatial columns, which also gives the metadata layer and the agent a richer, more realistic catalog
to reason over. The cut line was revised: viewer *polish* stays cuttable, but a recognisable city,
visible inhabitants, visible condition, and working levers are not.

The instrumentation rule is unchanged and now has a stated boundary: showing the city is the
product, showing measurements of the city is what we removed. A potholed road is the city; a
"road quality: 34%" label is instrumentation. Lever positions are the player's own input and are
exempt.

## 2026-08-02 — Simulation scale and tick grain

**Context.** Open question: how many citizens and how fine a tick to hit "millions of rows" honestly
without making a 20-year run impractical.

**Decision.** Monthly ticks. 32×32 grid. ~1,400 initial households (~3,100 citizens at seed 42),
growing via migration. History tables snapshot citizens, tiles, buildings, roads, and commutes every
month. Each `uv run sim` truncates the warehouse then rewrites.

**Rationale.** Monthly grain × a few thousand citizens × ~241 snapshots (initial + 20×12) yields
about 2.1M rows across warehouse tables in under 30s on this host — enough volume for the agent to
feel real SQL pressure without multi-hour loads. Sub-monthly ticks would inflate volume further for
little causal insight.

**Consequences.** Knobs live in `blindcity.sim.city_init` (`GRID_W`, `GRID_H`,
`INITIAL_HOUSEHOLDS`). Identity checks use in-memory fingerprints plus matching row counts across
two full warehouse runs on one seed. Observed seed-42 / 20-year total: **2,118,197** rows.

## 2026-08-02 — Causal graph module as the lineage source

**Context.** Slice 3 requires lineage generated from the simulation's equations, including a path
from income tax rate to revenue.

**Decision.** Declare directed edges once in `blindcity.sim.causal.CAUSAL_EDGES`. The monthly systems
implement those relationships; `blindcity.catalog.emit` walks the same structure for table- and
column-level DataHub lineage. No hand-authored GraphQL lineage blobs.

**Rationale.** One graph cannot drift between the model and the catalog. The direct edge
`lever_monthly.income_tax_rate → budget_monthly.income_tax_revenue` is the path judges care about;
longer satisfaction → migration → population → revenue edges remain for exploration.

**Consequences.** Adding a system requires adding causal edges if the catalog should show it. The
baseline (`datahub-emit --baseline`) skips glossary, lineage, and descriptions entirely.

## 2026-08-02 — Baseline catalog table names

**Context.** Open question: how realistically opaque should baseline table names be?

**Decision.** Short realistic warehouse-ish names (`t_person_m`, `t_budg_m`, `t_policy_m`, …), not
gibberish and not the full semantic names. Documented in README when the control arm is explained.

**Rationale.** Fair control: an agent with SQL alone can still query, but without glossary or lineage
it must rediscover meaning. Names that look like a rushed ETL dump are more honest than
`table_01`.
