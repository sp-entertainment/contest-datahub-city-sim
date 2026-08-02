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
