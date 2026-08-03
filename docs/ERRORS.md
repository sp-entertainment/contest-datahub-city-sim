# Errors

Log problems hit and how they were resolved, so they are not rediscovered.

## Known traps, recorded before they bite

### MCP mutation tools missing from the tool list

**Symptom.** Tools such as `add_tags` never appear, with no error.

**Cause.** Mutations are off by default and unregistered tools are silently absent.

**Fix.** Set `TOOLS_IS_MUTATION_ENABLED=true` in the MCP server configuration.

### "Generate new token" greyed out in Settings

**Symptom.** Cannot create a GMS access token from the UI.

**Cause.** Metadata Service Authentication is off by default in OSS.

**Fix.** Set `METADATA_SERVICE_AUTH_ENABLED=true` on both the `datahub-gms` and
`datahub-frontend-react` containers, then restart. Note that `datahub docker quickstart` hardcodes
`METADATA_SERVICE_AUTH_ENABLED: 'false'` for GMS and re-downloads the compose file on every run, so an
`.env` variable will not override it — the compose file must be edited and pinned.

**Applies to us?** Not currently. We run unauthenticated against `localhost:8080/api/graphql`.

### Quickstart exhausts memory

**Symptom.** Containers restart, OpenSearch or Kafka dies.

**Cause.** Quickstart needs 8 GB RAM, 2 GB swap, and 13 GB disk for its 14 containers.

**Fix.** Use a machine with 16 GB or more, since Postgres, the agent, and a browser run alongside.

**Update, 2026-08-01.** Quickstart `v1.5.0.6` brings up six containers, not fourteen — the current
`quickstart` compose profile is much leaner than this note assumed. The memory guidance still holds
as a floor. See `docs/ENVIRONMENT.md` for the observed container list.

## Problems hit

### `uv` not found immediately after `winget install`

**Symptom.** `winget install --id=astral-sh.uv` reports success, then `uv --version` in the same
shell fails with a command-not-found.

**Cause.** winget updates the machine and user PATH in the registry. An already-open shell keeps the
PATH it was started with.

**Fix.** Open a new shell, or rebuild PATH in place:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
```

Non-interactive tool sessions cannot "just open a new terminal", so the in-place rebuild is the one
that matters for agents.

### `HOME variable is not set` warnings during quickstart

**Symptom.** `datahub docker quickstart` emits repeated
`level=warning msg="The \"HOME\" variable is not set. Defaulting to a blank string."`

**Cause.** The compose file references `$HOME`, which Windows does not define — it uses `USERPROFILE`.

**Fix.** None needed. Cosmetic. All six containers came up healthy regardless. Do not chase it.

### `uv trampoline failed to canonicalize script path` for `datahub`

**Symptom.** `datahub version` fails immediately with a trampoline canonicalize error after the tool
was installed earlier.

**Cause.** The uv tool install for `acryl-datahub` was removed or its venv moved, leaving a stale
`~/.local/bin/datahub.exe` shim.

**Fix.**

```powershell
uv tool install --python 3.11 --force "acryl-datahub[datahub-rest]"
```

### Docker Desktop engine pipe vanishes mid-session

**Symptom.** `docker ps` / Postgres / DataHub all fail with
`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified` after a
successful start. Containers show `Exited (255)` after the daemon returns.

**Cause.** Docker Desktop (Windows) restarted or crashed; the named pipe goes away with the engine.
Heavy concurrent container starts right after a cold launch can also leave the engine unstable.

**Fix.** Fully quit Docker Desktop processes, relaunch `Docker Desktop.exe`, wait until
`docker info` succeeds twice ~10s apart, then `docker compose … up -d` for Postgres and
`docker start` the datahub-* containers (or `datahub docker quickstart`). Re-run `uv run sim` —
it truncates and rewrites the warehouse, so a partial run is not fatal.

### Road congestion was pinned at 1.0 on every segment

**Symptom.** None visible. The simulation ran, all tests passed, and `road_monthly.congestion` was
written for every segment every month. The column was simply the constant 1.0.

**Cause.** `congestion = traffic / (40 * (1 - 0.6 * wear))`. Measured per-segment traffic had a
median of ~89 against a capacity of 16–40, so the `min(1.0, …)` clamp fired on all 458 segments for
the whole run. Road wear cannot move a value already at its ceiling.

**Why it mattered more than it looked.** It severed a whole branch of the causal graph:
wear → congestion → commute travel time → satisfaction → migration. Every downstream effect of road
maintenance was dead, and the agent would have been handed a column that never varies — the exact
opposite of what an analytics agent is meant to reason over. Nothing failed, which is why it
survived a full slice.

**Fix.** `SEGMENT_CAPACITY = 150.0` in `systems.py`, sized against observed traffic. Mean congestion
is now ~0.76 with no saturated segments. Guarded by
`tests/test_causal_validation.py::test_congestion_is_not_saturated`.

**Found by** validating each declared lineage edge against the simulation — wear → congestion was
the one edge that could not be demonstrated. A dead column is invisible to tests that only assert a
value is within range; it is obvious the moment you require the edge to actually move.

### Road maintenance could never reduce wear

**Symptom.** Recovery policies in the benchmark spent millions on roads and service score stayed
flat; mean wear still climbed.

**Cause.** `wear_repair = (monthly_budget / n_segments) / 500_000` effectively divided by segment
count twice. At any legal budget, repair was ~0.001/month while traffic-driven wear was ~0.01+/month.

**Fix.** Citywide scaling: `wear_repair = (annual_budget / 1_000_000) * 0.01`, and raise the lever
max to 8M so aggressive recovery can reverse neglect inside a 36-month turn budget. Recorded in
`docs/DECISIONS.md` (lever calibration).

### The health index rewarded the do-nothing policy

**Symptom.** None. 93 tests passed and the scenario looked correctly calibrated: the recovery
policy reached green, the neglect policy did not.

**Cause.** Three separate saturations inside the index, found by sweeping levers rather than
reading tests:

- Neglect finished at solvency **1.0000** versus recovery's 0.9914. Spending nothing repays debt
  and builds cash cover, so the component rewarded exactly the behaviour it was meant to punish.
- `water_sewer_capex` could not move its own score at any legal setting — capacity growth was
  `(annual/12)/50_000`, roughly 13 units/month at maximum against a deficit of 2,100. The water
  third of `service` was constant at 0, and spending on water strictly lowered the final index.
- `road_maintenance_budget` was flat from 0 to 1M. Flat repair against wear bounded in [0, 1]
  means every budget below break-even pins at 1.0 and every budget above it pins at 0.0. The
  lever's default sat inside the flat region.

**Fix.** Deferred maintenance liability folded into solvency; exponential debt decay; wear-
proportional road repair; water capex rescaled. See `docs/DECISIONS.md`, same date.

**Why it kept happening.** This is the third saturated quantity found in this codebase after road
congestion and the road repair formula, and all three passed their tests. Asserting a value is
within range is satisfied by a constant, and asserting the composite score orders two policies
correctly is satisfied by three broken components and one working one. The assertions that catch
it require a value to **move**, and require the winning arm to beat the losing arm **component by
component**.

### `UnicodeEncodeError` on the final status line of a command that worked

**Symptom.** `uv run datahub-emit --evaluate-assertions` wrote all 17 tables, 20 glossary terms,
29 lineage edges and 9 assertion results, then died with
`'charmap' codec can't encode character '\u2192'` and exited non-zero.

**Cause.** Python binds stdout to the Windows console's legacy code page (cp1252 here). Any
character outside it raises at print time. Our output is full of en dashes, arrows and ellipses —
glossary text, column descriptions, the lineage hint — so the work succeeded and the report killed
the process. `datahub docker quickstart` has the same bug with its `✔`, which is why its last line
is a traceback even on a successful bring-up.

**Fix.** `blindcity.console.configure_console()` switches stdout and stderr to UTF-8 with
`errors="replace"`, called first thing in all four entry points. Nothing to do about the DataHub
CLI's own copy of the bug; ignore its traceback and check `docker ps` instead.

**Worth knowing.** A non-zero exit here means nothing about whether the catalog was written. Check
the emitted counts, not the exit code, when this pattern appears in a tool that is not ours.

### Congestion re-saturates over a long run

**Symptom.** `road_monthly.congestion` in the seed-42 / 20-year warehouse load: 24% of rows at
exactly 1.0 overall, and 59.6% by tick 240.

**Cause.** `SEGMENT_CAPACITY` is a fixed 150 while traffic scales with population. Over 20 years
the city outgrows the constant, so the `min(1.0, ...)` clamp starts firing again — the same ceiling
as the original congestion bug, arriving late instead of immediately. The 36-turn benchmark
scenario is too short to hit it, so the tests do not catch it.

**Status.** Open. The warehouse history is exactly what the agent arms query for patterns, so a
column that is 60% pinned by the end of the record is degraded evidence. Candidate fix: replace the
hard clamp with an asymptotic map (`ratio / (1 + ratio)`) so congestion never reaches its bound and
stays strictly ordered at every traffic level — this needs the downstream commute-time and service
calibrations revisited, since it changes what "congestion = 0.5" means.
