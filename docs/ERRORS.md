# Errors

Log problems hit and how they were resolved, so they are not rediscovered.

## The one pattern worth internalising before you read anything else

**Four times now this project has shipped a column or a score that was pinned at a constant, and
every one of them passed a full green test suite.** Road congestion (twice), the road repair
formula, the water term in `service`, and solvency in the health index.

They survive because the obvious assertion is a range check, and *a constant is always in range*.
Asserting `0 <= congestion <= 1` is satisfied by `congestion = 1.0` on every row forever. Asserting
that a good policy outscores a bad one is satisfied by three broken components and one working one.

The assertions that actually catch it:

- Require a value to **move** when its input moves, not merely to sit inside bounds.
- Require the winning mode to beat the losing mode **component by component**, not just on the total.
- Check the **fraction at the ceiling**, not the mean. A mean of 0.88 hid 24% of rows at exactly
  1.0; see the `at ceiling` column and query in `docs/ENVIRONMENT.md`.
- Sweep a lever across its **whole range** and require every step to change the outcome. Flat
  regions are where a controller starting from the default will probe first.

This matters more here than in most codebases: the entire project rests on an agent diagnosing a
city from its data. A column that never varies is not a cosmetic defect, it is a missing sense
organ — and it is invisible from the test output.

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

**Fix.** `powershell -ExecutionPolicy Bypass -File infra/stack.ps1` — it launches Docker Desktop if the daemon is down, waits for it,
and brings the containers up in order. Only fall back to relaunching by hand if that fails.

**Superseded, 2026-08-03.** The `Exited (255)` part of this entry was misdiagnosed. 255 is what the
daemon records when it kills a *running* container during its own shutdown; it is not a crash and
the containers are not unstable. See "DataHub containers never come back after a Docker restart"
below for what was actually happening.

**Stale advice removed.** This entry used to say a partial run was not fatal because `uv run sim`
truncates and rewrites the warehouse. It no longer truncates — append-by-`run_id` became the
default so benchmark modes can write in parallel. A partial run now leaves a partial `run_id` in the
warehouse. Use `--reset-warehouse` if you want the old behaviour, or just ignore the stray run,
since everything is scoped by `run_id` anyway.

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

**Fix.** `SEGMENT_CAPACITY = 150.0` in `systems.py`, sized against observed traffic.

**This fix was not enough — see "Congestion re-saturates over a long run" below.** Resizing a
constant only moves the point at which a clamp starts firing; it does not stop it firing. The
column pinned again once the city outgrew 150, and the real fix was to remove the clamp. The
guard named here (`test_congestion_is_not_saturated`) was also too weak to catch the recurrence
and has been replaced by three stricter tests.

**Found by** validating each declared lineage edge against the simulation — wear → congestion was
the one edge that could not be demonstrated. A dead column is invisible to tests that only assert a
value is within range; it is obvious the moment you require the edge to actually move.

### Road maintenance could never reduce wear

**Symptom.** Recovery policies in the benchmark spent millions on roads and service score stayed
flat; mean wear still climbed.

**Cause.** `wear_repair = (monthly_budget / n_segments) / 500_000` effectively divided by segment
count twice. At any legal budget, repair was ~0.001/month while traffic-driven wear was ~0.01+/month.

**Fix.** Citywide scaling: `wear_repair = (annual_budget / 1_000_000) * 0.01`, and raise the lever
max to 8M so aggressive recovery can reverse neglect inside the 36-month recovery window. Recorded in
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
it require a value to **move**, and require the winning mode to beat the losing mode **component by
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
as the original congestion bug, arriving late instead of immediately. The benchmark
scenario is too short to hit it, so the tests did not catch it.

**Why it mattered more than the 20-year figure suggested.** At benchmark crisis onset congestion
was pinned on **100% of segments**, and the 60 months of neglect history an agent can query were
flat 1.0 throughout. The column an agent reads to work out that the roads are the problem was a
constant during exactly the phase where diagnosing it is the entire test. It unpinned by turn 5
once repair began — so the ceiling landed on the diagnostic window and nowhere else.

**Fix.** `congestion = 1 - exp(-ratio)`. Asymptotic rather than clamped, so it approaches 1.0
without reaching it and stays strictly ordered at every traffic level. The exponential is close to
the identity for ratios well under 1, so values that were already informative barely moved and the
downstream commute-time and service-score calibrations did not need revisiting — confirmed by the
benchmark invariants still holding (neglect fails, defaults fail, recovery reaches green).

Warehouse after the fix: congestion 0.000–0.728, mean 0.586, **0% at the ceiling** at every tick.
Crisis onset now spans 0.671–0.847 across segments instead of a flat 1.0.

**One caveat, recorded so nobody trips on it.** The map saturates numerically beyond roughly 35×
capacity, where `1 - exp(-ratio)` rounds to 1.0 in float64. Observed ratios peak near 2×, so this
is far outside anything the simulation produces — but it is a real bound, not an unbounded map.

**Guarded by** `test_congestion_never_reaches_its_ceiling` (2-year and 20-year horizons),
`test_congestion_stays_ordered_as_traffic_rises`, and
`test_congestion_is_informative_at_benchmark_crisis_onset`. The previous guard asserted only that
*some* segment was unsaturated and that the mean sat below 0.98 — which a 99%-pinned column passes.

### Assertions pooled every run in the warehouse

**Symptom.** `datahub-emit --evaluate-only` reported `n=1614574` for `citizen_monthly` when a
single run holds 808,597 rows. All nine assertions passed.

**Cause.** The assertion SQL had no `WHERE run_id`, dating from when `uv run sim` truncated on
every launch and the warehouse only ever held one run. Once append became the default, the two
row-count assertions (`minimum=1000`, `minimum=10000`) got easier every time anyone loaded the
simulation, and the range assertions silently pooled runs that exist to be compared. With three
benchmark modes writing concurrently this would have reported one verdict over all three.

**Fix.** Every predicate takes an optional `run_id`, bound as a parameter rather than
interpolated. `datahub-emit` defaults to the most recent run, `--run-id` selects another, and
`--all-runs` opts into the old pooled behaviour deliberately. The evaluated scope is printed with
the summary line so a pooled result cannot be mistaken for a scoped one.

### DataHub containers never come back after a Docker restart

**Symptom.** The engine restarts (update, crash, reboot) and afterwards only `blindcity-postgres`
and `datahub-mysql-1` are running. The five DataHub quickstart containers sit at `Exited (255)`.
Starting them all at once then produces a fresh round of 255s, which looks like a cascading
dependency failure.

**Cause.** Two things, neither of which is a cascade.

1. **Restart policy.** DataHub's quickstart compose sets `restart: no` on its containers. Our
   `infra/postgres/docker-compose.yml` sets `unless-stopped`. So on every engine restart Postgres
   heals itself and DataHub does not — the asymmetry that made this look like DataHub-specific
   flakiness.
2. **Exit 255 is not a fault.** `OOMKilled=false`, empty `State.Error`, `RestartCount=0`. 255 is
   what the daemon records when it terminates a *running* container during its own shutdown. It is
   a shutdown signature, not a crash signature, and reading it as a crash sends you looking for a
   bug that is not there.

The genuine ordering constraint is real but smaller than it appears: OpenSearch and Kafka must be
healthy before GMS will start cleanly.

**Fix.** `infra/stack.ps1`. Starts everything in dependency order, waits on health at each tier,
then applies `docker update --restart unless-stopped` to all seven so the next engine restart
recovers by itself. Idempotent — safe to run when things are already up.

```powershell
powershell -ExecutionPolicy Bypass -File infra/stack.ps1            # bring up and verify
powershell -ExecutionPolicy Bypass -File infra/stack.ps1 -Status    # report only, changes nothing
```

**The catch.** `datahub docker quickstart` *recreates* its containers and re-downloads its compose
file, which resets the policy to `no`. Re-run `infra/stack.ps1` after any quickstart.

**Also worth setting.** Docker Desktop's `AutoStart` is `False` on this host, so a reboot leaves
the daemon down entirely. Enable "Start Docker Desktop when you sign in" in Settings > General if
you want the stack to survive a restart unattended.

### `docker start @array` splats a single-element result one character at a time

**Symptom.** `Error response from daemon: No such container: d` / `: a` / `: t` ... one line per
letter of the container name.

**Cause.** `Where-Object` returns a bare string when exactly one item matches, not an array.
Splatting a string with `@` passes each character as a separate argument.

**Fix.** Force an array with `@(...)` around the pipeline, and pass it to the native command
directly (`docker start $present`) rather than splatting. Note this failure was invisible while the
container happened to be running already — the script reported success. Test recovery paths by
actually stopping the thing first.

### Docker Desktop dies on startup: "initializing Inference manager"

**Symptom.** Docker Desktop shows *An unexpected error occurred… needs to close*, with:

```
starting services: initializing Inference manager: listening on
unix://C:/Users/spect/AppData/Local/Docker/run/dockerInference:
remove …/dockerInference: The file cannot be accessed by the system.
```

The daemon never comes up, `com.docker.service` stays `Stopped`, and `docker` commands hang or
report the missing named pipe.

**Cause.** An unclean shutdown leaves orphaned AF_UNIX socket files in
`%LOCALAPPDATA%\Docker\run` — zero-byte entries with the `ReparsePoint` attribute. Docker tries
to remove one before rebinding it and cannot. Neither can anything else: Windows will not open an
orphaned socket reparse point through normal file APIs, so `Remove-Item -Force` fails on each with
"The file cannot be accessed by the system."

**Fix.** Quit Docker, then rename the whole directory. Docker recreates it on next start.

```powershell
Get-Process | Where-Object { $_.ProcessName -like "*ocker*" } | Stop-Process -Force
Rename-Item "$env:LOCALAPPDATA\Docker\run" "run.stale"
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

Renaming the parent works where deleting the children does not, because it never opens them. The
leftover directory holds 0 bytes and can be deleted after the next reboot, which releases the
kernel objects.

**Do NOT click "Reset to factory defaults".** It sits next to Quit in that dialog and destroys
every container and volume — the warehouse's run history and the entire DataHub catalog — to fix
three empty files. Both are rebuildable (the simulation is deterministic and `datahub-emit`
reruns) but it is hours of work for nothing.

### `infra/stack.ps1` threw instead of starting a stopped Docker

**Symptom.** With the daemon down, the script exited with a `NativeCommandError` from its own
`docker info` probe rather than launching Docker Desktop.

**Cause.** `$ErrorActionPreference = 'Stop'` turns a native command's *stderr* into a terminating
error in Windows PowerShell 5.1. A dead daemon writes to stderr, so `Test-Daemon` threw in exactly
the case it exists to detect.

**Fix.** Relax the preference around the probe and test `$LASTEXITCODE`, not `$?`. Every earlier
run had Docker already up, which is why a function whose entire purpose is the down case had never
executed its down path.
