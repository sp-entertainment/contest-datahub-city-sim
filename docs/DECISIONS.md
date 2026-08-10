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

| Mode | Controller | Sees |
| --- | --- | --- |
| `human` | A person | The city render, the levers, and the upstream Analytics Agent to ask questions |
| `agent_datahub` | Our auto-mode agent | DataHub over MCP, plus SQL against the warehouse |
| `agent_raw` | Our auto-mode agent | SQL against the warehouse only, no catalog context |

**Rationale.**
- **Simulation fidelity is what makes the result mean anything**, so effort belongs there. A crisis
  that is trivially recoverable, or unrecoverable regardless of skill, measures nothing.
- **Three modes separate two different questions.** `agent_datahub` vs `agent_raw` isolates the value
  of the metadata. `human` vs `agent_datahub` says whether the automation is worth having at all.
  Giving the human the Analytics Agent makes them a realistic operator-with-tooling baseline rather
  than a strawman.
- **A composite index gives one comparable number** with a component breakdown for the writeup, and
  a trajectory that plots well in a three-minute video.
- We wrote the simulation, so ground truth exists and the experiment is repeatable — which no real
  data team can do with their own history.

**Consequences.**
- **The viewer is demoted to cosmetic.** It does not need to represent the city faithfully. It needs
  to look like a city and carry the lever controls for the human mode. This reverses the 2026-08-01
  decision that made a recognisable city never-cut; the levers stay required because the human mode
  cannot exist without them, but scene fidelity is now the first thing to cut.
- **Information parity becomes an experimental control, not an aesthetic rule.** Every mode must get
  the same channel to the city's state; only the metadata differs. The existing "no charts, no
  counters" rule now has a stronger justification than the original one: a numeric readout in the
  viewer would hand the human mode an information channel the agent modes do not have, and invalidate
  the comparison.
- **Lever bounds stop being placeholders.** They determine whether a crisis is recoverable, so they
  need calibrating against an actual scenario.
- **Runs must be isolated in the warehouse.** Modes run in parallel and all write history; without a
  run identifier they overwrite each other. The schema needs a `run_id`, and the sim must stop
  truncating shared tables.
- New work that existed in no slice: scenario definition, health index and green threshold, turn
  budget, a controller interface the three modes implement, a run harness, and a results format.

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
gibberish and not the full semantic names. Documented in README when the control mode is explained.

**Rationale.** Fair control: an agent with SQL alone can still query, but without glossary or lineage
it must rediscover meaning. Names that look like a rushed ETL dump are more honest than
`table_01`.

## 2026-08-02 — Composite health index weights and green threshold

**Context.** Slice 5 needs one comparable score per run with a component breakdown. The four
required components are solvency, citizen satisfaction, service coverage, and population retention.

**Decision.**

| Component | Weight | What it measures |
| --- | ---: | --- |
| solvency | 0.20 | Treasury months-of-cover vs operating spend, debt per capita, monthly balance |
| satisfaction | 0.30 | Mean citizen satisfaction (0–1) |
| service | 0.30 | Equal thirds: power coverage×reliability, water headroom, road wear/congestion |
| population | 0.20 | Retention vs founding population at scenario seed (tick 0) |

Green threshold: **0.62**. "Recovered" means the composite crossed 0.62 at least once within the
turn budget.

**Rationale.**
- **Service and satisfaction carry the thesis.** Metadata helps an agent find *why* the city is
  sick (roads, water, power, tax pressure). Weighting those at 0.30 each keeps the score sensitive
  to the causal chains the catalog exposes. Solvency at 0.20 prevents a pure tax-and-hoard policy
  from winning without fixing services; population at 0.20 rewards retaining people without letting
  a single migration blip dominate.
- **Solvency uses months-of-cover, not raw treasury.** Extractive neglect can stockpile cash while
  infrastructure dies; measuring buffer against operating spend stops that from looking "perfectly
  solvent."
- **0.62 is calibrated against `infrastructure_neglect`.** Crisis onset scores ~0.38. A deliberate
  bad policy never crosses green (final ~0.42). A hand-tuned recovery policy crosses at turn ~31 of
  36 and finishes ~0.65. The threshold is high enough that recovery is non-trivial and low enough
  that a competent policy wins inside the budget.

**Consequences.** Weights and threshold live in `blindcity.benchmark.health`. Changing them is a
design change, not a silent tweak — update this entry if they move.

## 2026-08-02 — Scenario: infrastructure_neglect

**Context.** The benchmark needs one crisis that is seedable, recoverable, and losable.

**Decision.** Scenario `infrastructure_neglect` (seed 42): 60 months of underfunded services and
high utility costs, then a fiscal/capacity shock (thin treasury, elevated debt, water capacity cut,
road wear floor, satisfaction cap). Controllers get 36 monthly turns to recover.

**Rationale.** Pure multi-year neglect with any positive tax rate left the treasury enormous and the
composite above green, measuring nothing. The shock represents a debt reckoning on top of worn
infrastructure without inventing a second simulation. Hand-played good policy (fund roads/water,
hedge power, moderate taxes, open zoning) recovers; continued neglect fails.

**Consequences.** Implemented in `blindcity.benchmark.scenario`. Additional scenarios can share the
same harness.

## 2026-08-02 — Lever bound calibration for recovery

**Context.** Lever bounds were placeholders. Road repair math divided maintenance by segment count
in a way that made net wear reduction impossible at any budget inside the old 5M max.

**Decision.**
- Fix road repair to citywide scaling: `$1M/year ≈ 0.01 wear reduction per segment per month`.
- Raise `road_maintenance_budget` max 5M → **8M**, default 500k → **600k**.
- Raise `water_sewer_capex` max 5M → **8M**, default 400k → **500k**.

**Rationale.** Calibration runs showed good policy stuck with service ~0.23 because roads could not
heal. After the formula fix and higher caps, good recovery reaches green; bad still fails. Defaults
nudge slightly toward sustainability so a no-op controller is not as catastrophic as pure zero.

**Consequences.** In-memory fingerprints and warehouse row counts from earlier 2026-08-02 runs are
stale again (alongside the `SEGMENT_CAPACITY` change). Re-record when Postgres is available.

## 2026-08-02 — Warehouse append-by-run_id (no default truncate)

**Context.** Modes write history in parallel; global truncate made multi-mode runs impossible.

**Decision.** Default `uv run sim` calls `ensure_schema` and `start_run` only. Truncate is opt-in
via `--reset-warehouse` for clean demo loads.

**Rationale.** Every table already carries `run_id`. Truncating was a convenience that became a
correctness bug under the benchmark framing.

**Consequences.** Repeated CLI demos accumulate runs unless `--reset-warehouse` is passed.
## 2026-08-02 — The health index scored the neglect mode as solvent

**Context.** A review of the Slice 5 benchmark ran lever sweeps against the finished index rather
than reading its tests. Three components turned out not to measure what they claimed.

- **Solvency rewarded neglect.** The do-nothing mode finished at solvency **1.0000**; the recovery
  mode at 0.9914. Spending nothing repays the shock debt and builds months of cash cover, so on
  cash alone neglect is indistinguishable from prudence. Twenty per cent of the index was pointing
  the wrong way, and the previous entry's claim that months-of-cover prevented this was false.
- **Water capex was a trap.** With capex at 5.5M the load ratio still ended at 1.61, which scores
  zero. Raising it to the 8M maximum *lowered* the final index (0.653 → 0.546) because it cost
  treasury and bought nothing. A third of `service` was pinned at 0 and correctly diagnosing the
  water system was punished.
- **The road lever was flat where a controller starts.** Budgets of 0, 600k and 1M produced
  identical final indices to four decimals — flat repair against bounded wear means everything
  below break-even pins at wear 1.0 and everything above it pins at 0.0. The default sat inside
  the dead zone, so incremental probing returned no signal at all.

**Decision.**
- Add a **deferred maintenance liability** to solvency. Road wear and the missing water capacity
  are priced (`ROAD_RESTORE_COST_PER_SEGMENT`, `WATER_RESTORE_COST_PER_UNIT`) and added to debt.
  Reweight solvency to `0.30` cover / `0.50` debt / `0.20` balance.
- Make the debt term decay **exponentially** (`DEBT_PER_CAPITA_SCALE = 3000`) instead of clamping
  linearly to zero, which had pinned the neglect mode's solvency at a constant for all 36 turns.
- Make road repair **proportional to existing wear** (`ROAD_REPAIR_RATE_PER_MILLION = 0.05`), so
  wear settles at a budget-dependent equilibrium instead of slamming into a bound.
- Retune water capex to `WATER_CAPEX_PER_UNIT = 6000` so the top of the range can bring the load
  ratio back under target inside the turn budget.
- Widen `population_score` so parity with the founding population scores ~0.71 rather than 1.0;
  it had been pinned at 1.0 for every turn of a successful run.

**Rationale.** Deferred maintenance is how municipal finance already describes this — a government
that balances its books by letting the assets rot is carrying a real liability — so the fix is
honest rather than a fudge factor. The saturation fixes share one principle: **a component that
cannot move cannot be diagnosed**, and the whole benchmark rests on an agent diagnosing the city
from its data.

**Consequences.** Calibrated results, seed 42, `infrastructure_neglect`:

| Policy | Final index | Green | solvency | satisfaction | service | population |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Crisis onset | 0.328 | — | | | | |
| Neglect | 0.303 | never | 0.539 | 0.251 | 0.217 | 0.272 |
| Defaults (no action) | 0.437 | never | 0.582 | 0.433 | 0.324 | 0.464 |
| Recovery | 0.797 | turn 14 | 0.976 | 0.716 | 0.772 | 0.775 |

Recovery now beats neglect on **every** component, not just the composite. Both budget levers are
monotone with an interior optimum, so the benchmark cannot be won by slamming everything to maximum
without reading the city's condition. Doing nothing loses, which is what makes the run a test of
the controller. Sim behaviour changed, so fingerprints and warehouse counts are stale again.

**Guarded by** the regression block at the end of `tests/test_benchmark.py`. Every one of these
defects passed the existing range-style assertions — a component that is constant, inverted, or
saturated is still in [0, 1].

## 2026-08-03 — Congestion is asymptotic, and assertions are scoped to a run

**Context.** With the stack finally up, a live warehouse load exposed two defects that only appear
against real data at real volume.

**Decision 1: replace the congestion clamp with `1 - exp(-ratio)`.** `min(1.0, traffic/capacity)`
put the column on its ceiling for 24% of rows across a 20-year load, 59.6% by tick 240, and — the
part that actually matters — **100% of segments at benchmark crisis onset**, holding flat through
all 60 months of neglect history.

**Rationale.** That history is what an agent queries to work out why the city is failing, and the
scenario is built so the roads are a large part of the answer. A constant column there means both
modes are guessing, which collapses the one comparison the project exists to make. The exponential
is close to the identity for ratios under 1, so previously-informative values barely moved and the
commute-time and service-score calibrations held without adjustment.

**Decision 2: assertions evaluate one `run_id` by default.** The SQL had no run filter, a holdover
from when `uv run sim` truncated on launch. `--run-id` selects a specific run, `--all-runs` opts
back into pooling, and the scope is printed with the results.

**Rationale.** Append-by-`run_id` was adopted so modes could write in parallel; leaving the
assertions unscoped meant the quality gate reported a single verdict across modes that exist to be
compared, and the row-count assertions got easier with every load. A gate that loosens as data
accumulates is worse than no gate.

**Consequences.** Warehouse re-recorded (`run_id=35`): congestion 0.000–0.728, mean 0.586, 0% at
the ceiling at every tick. Benchmark invariants unchanged — neglect 0.324 (never green), defaults
0.455 (never green), recovery 0.813 (green at turn 13). Fingerprints shift again, since congestion
feeds commute time, satisfaction and migration.

## 2026-08-06 — Quarterly decisions, and "modes" instead of "arms"

**Context.** The scenario gave the controller 36 monthly turns. Two problems surfaced together
once the loop actually ran against a hosted model.

**Decision 1: twelve quarterly turns instead of thirty-six monthly ones.** `turn_budget=12`,
`months_per_turn=3`. The recovery window is unchanged at 36 simulated months.

**Rationale.** Three separate reasons pointed the same way.

- **The human mode has to play this too.** Thirty-six rounds of lever-pulling is tedious rather
  than interesting, and a human who disengages halfway is not a fair comparison for an agent that
  does not get bored.
- **Cost.** Each agent turn is several LLM round trips, because the model must see each query
  result before choosing the next one. Thirty-six turns ran to hundreds of calls per mode, per
  seed. Twelve turns puts a full run in the dozens.
- **Realism, and a sharper test.** Cities are not re-planned monthly; quarterly budget review is
  the real cadence. Fewer chances to correct also put more weight on each individual diagnosis —
  which is exactly the thing the catalog is supposed to improve, so the change strengthens the
  measurement rather than diluting it.

**Consequences.** Calibration is unchanged, because it is the same levers over the same 36
months: crisis onset 0.338, neglect 0.324 (never green), defaults 0.455 (never green), recovery
0.813, now reaching green at turn 4 of 12 rather than turn 13 of 36.

**Decision 2: the three controllers are "modes", not "arms".** Renamed throughout the code, the
docs, and the results format.

**Rationale.** "Arm" is borrowed from clinical trials — treatment arm, control arm — and is
meaningless outside that context. The project's own original framing said "control modes: human
pulling levers, AI with DataHub, AI without DataHub", which is clearer and is what a judge will
understand without translation. The jargon crept in from thinking about experimental design; the
plainer word was there first.

**Consequences.** `RunResult.arm` is now `RunResult.mode` and `--arm` is now `--mode`. Done before
any scored results existed, so no recorded data uses the old field name.

## 2026-08-10 — Every mode runs gpt-4o

**Context.** The benchmark had been running `gpt-5.6-luna`. Adding `agent_analytics`, which
delegates to DataHub's own Analytics Agent, exposed a hard constraint: that agent cannot drive any
`gpt-5.6-*` model at all. It needs function tools, it calls `/v1/chat/completions`, and the whole
gpt-5.6 family refuses that combination unless reasoning is disabled — which the agent has no way
to do, since it never sets `reasoning_effort` and exposes no option for it. Every question returned
a `400`.

Searching all 72 commits of that repository: `reasoning_effort` and `use_responses_api` have never
appeared, and no gpt-5 model has ever been referenced in its source, README, or model picker. Its
OpenAI integration was written for `gpt-4o` and `gpt-4o-mini`, they are the only two options its
setup wizard offers, and `gpt-4o` is labelled "Recommended".

**Decision.** All four modes run **`gpt-4o`**. The Analytics Agent runs entirely unmodified.

**Rationale.** Two reasons, and the second is the stronger one.

The narrow reason is compatibility: `gpt-4o` is what the Analytics Agent supports, so it is the
only model on which every mode can run without patching a third-party component. A run that
depended on our modification of DataHub's agent would carry an asterisk nobody should have to
explain.

The broader reason is that a shared model is what makes the arms comparable at all. With every
mode on one model, the only thing that varies between them is the tools and context each is given
— which is the quantity the benchmark exists to measure. Different models across arms would mean
every gap had two candidate explanations, and no way to separate them.

**Consequences.**

- `gpt-4o` is not a reasoning model and rejects `reasoning.effort` outright. `ResponsesClient` now
  drops the parameter on the first refusal and records `reasoning_sent` in the report, so a run
  where the budget was applied and one where it was silently discarded do not look identical.
  Every mode shares one client, so this flips for all of them at once.
- Absolute scores are not comparable with anything recorded before this date. Earlier results in
  `docs/RESULTS.md` were produced on `gpt-5.6-luna` at reasoning effort `low`, and are labelled.
- `gpt-4o` is an older model. Some of the behaviour the newer model showed — holding a plan across
  twelve turns, recovering from a fan-out join — may not survive, and a drop in every arm at once
  is the expected shape rather than a regression in any one of them.
