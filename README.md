# City Sim Agent Benchmark

**A benchmark for whether data catalogs make AI agents better at their job.**

A city simulation runs, producing hundreds of thousands of rows into Postgres — citizens,
households, roads, power, water, budget, month by month. Then it is put into a crisis, and an agent
is asked to get it out using eight policy levers and twelve quarterly decisions.

The agent cannot see the city. It can only query the warehouse. What changes between runs is **how
much the catalog tells it about that warehouse** — and we measure what that is worth.

Built for [Build with DataHub: The Agent Hackathon](https://datahub.devpost.com/).

## The result

Same model, same seed, same crisis, same levers, same turn budget. The only difference is what
DataHub gave each agent.

One run per mode, seed 42, `gpt-5.6-luna` at reasoning effort `low`.

| Mode | What the catalog provides | Index | Green by | SQL queries |
| --- | --- | ---: | ---: | ---: |
| `agent_raw` | Nothing. Schema discovery via `information_schema` only | 0.6488 | turn 10 | 62 |
| `agent_datahub` | Descriptions, glossary, column-level lineage | 0.7187 | turn 5 | 59 |
| `agent_datahub_live` | The above, plus assertions read from DataHub each turn | **0.8187** | **turn 3** | **22** |
| `agent_analytics` | DataHub's own Analytics Agent answers instead | 0.6825 | turn 5 | — |
| *`good_policy`* | *hand-calibrated reference, not an agent* | *0.8132* | *turn 4* | *—* |
| *`bad_policy`* | *deliberate neglect, not an agent* | *0.3244* | *never* | *—* |

Green is 0.62. **The fully-catalogued agent beat the hand-tuned expert policy, reached green a turn
sooner, and used a third of the queries the uncatalogued agent needed.**

This is **one run per mode**, and run-to-run spread on repeats has reached 0.08 of final index —
larger than the `agent_raw` → `agent_datahub` gap above. That gap is not resolved by this data.
The `agent_datahub_live` margin is, and the ordering has held on every paired run so far.
`docs/RESULTS.md` has the full caveats; `blindcity compare` prints them itself.

The reference rows cost nothing to reproduce, no API key required:

```bash
uv run blindcity run --mode good_policy --out results/good.json
uv run blindcity run --mode bad_policy  --out results/bad.json
uv run blindcity compare "results/*.json"
```

### What we actually learned

The interesting result is not "catalogs help." It is *which kind* of metadata helped:

- **Descriptive metadata alone was worth little.** Across every paired run so far the
  `agent_datahub` / `agent_raw` gap has sat inside the run-to-run noise, and across four earlier
  pairs it ran +0.045, +0.043 and **−0.040** — the sign flipped, and a quantity that changes sign
  is not measuring what it claims to. Our table names are already human-readable, so a description
  saying `income_tax_revenue: Income tax collected` adds nothing the column name did not.
- **Prescriptive metadata transformed behaviour.** Assertions that document the operating range a
  healthy city holds to — and, just as importantly, which levers are *not worth tuning* — moved the
  agent from 0.7187 to 0.8187 and from green at turn 5 to turn 3 — and, tellingly, on *less* of
  everything: 22 queries against 59, and 19 LLM calls against 25. A mode that scored higher by
  querying more would just be a mode given more compute. This one stopped searching because it was
  told where to look.
- **Relationships the data cannot show are where lineage earns its keep.** Every lever is constant
  across the entire recorded history, so no amount of querying reveals that `income_tax_rate` drives
  `income_tax_revenue`. The catalog is the only place that relationship exists.

For a data platform team the practical reading is: documenting your columns will not make your
warehouse agent-ready. Documenting what *good* looks like might.

## How it is a benchmark

The city is the substrate, not the deliverable. A **scenario** puts it into a crisis (five years of
deferred maintenance plus a fiscal shock); a **controller** pulls levers over twelve quarterly
turns; a **composite health index** — solvency, satisfaction, service, population retention — scores
whether it recovered.

Four controllers face an identical seed, crisis, and budget:

| Mode | Who decides | What they can see |
| --- | --- | --- |
| `human` | You | The city render, the levers, and the Analytics Agent to ask questions |
| `agent_raw` | Our agent | SQL against the warehouse. No catalog |
| `agent_datahub` | Our agent | The same, plus DataHub descriptions, glossary and lineage |
| `agent_datahub_live` | Our agent | The same, plus assertions evaluated against the city each turn |

The three agent modes are **one implementation instantiated three times**. There is no `if mode ==`
anywhere in the loop, and `tests/test_agent.py` fails the build if the prompts, tools or turn
messages differ by anything other than the catalog block. That is the only way "they differ in
exactly one thing" is a property of the code rather than a promise in a document.

## Fairness, and where it is imperfect

Everything below is enforced by tests unless noted.

- **No mode is told the scoring function.** Not the index, not its components, not the threshold. An
  agent that knew the weights would optimise the metric instead of fixing the city.
- **No city-state numbers appear in any prompt.** Population, treasury and satisfaction are
  discoverable only through SQL.
- **The viewer shows no numbers either.** Worn roads look worn; unpowered buildings go dark. That is
  information parity with the agent modes, not a style choice.
- **Every run starts from an empty warehouse**, so no run inherits another's rows or planner
  statistics.
- **Assertions are derived from the simulation's own mechanics** and re-derived by
  `tests/test_operational_assertions.py`, which fails if a documented band stops matching what the
  code does. They state operating ranges and response times; they never name a lever to pull.

Known imperfections, stated plainly:

- **`agent_raw` is not fully blind.** `docs/DECISIONS.md` specifies a control catalog with opaque
  table names (`t_person_m`, `t_budg_m`) so the control would have to rediscover meaning. That
  catalog is built and emitted by `uv run blindcity emit --baseline`, but the agent modes query the
  real warehouse with its readable names, so the handicap was never applied. This is very likely why
  descriptive metadata showed no measurable effect.
- **One seed, one run per mode.** Three runs each was planned and cut for time. Run-to-run spread
  on repeats has reached 0.08 of final index, larger than the `agent_datahub`/`agent_raw` gap — so
  that gap is unresolved, and `blindcity compare` says so in its own output rather than leaving it
  to be noticed.
- **`agent_analytics` is a floor, not a ceiling.** Its DataHub connection was dead until the day of
  this run — an empty token meant zero context tools loaded — and the guidance that decides this
  benchmark was published to the catalog the same day. Handed that guidance directly, a prototype
  scored 0.8454 with green at turn 3, above every mode in the table.
- **The `human` mode has not been played end to end.** The lever panel and scene work.

## Quick start

Requires 16 GB RAM, 25 GB disk, Docker, Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
datahub docker quickstart          # DataHub Core on :9002, GraphQL on :8080
docker compose -f infra/postgres/docker-compose.yml up -d   # warehouse Postgres on :5432
uv sync --group dev
```

```bash
uv run blindcity sim --seed 42 --years 20    # generate a city into the warehouse
uv run blindcity sim --serve                 # viewer and lever panel on :8000
```

```bash
uv run blindcity run --mode good_policy --out results/good.json   # free reference: 0.8132
uv run blindcity run --mode bad_policy  --out results/bad.json    # free reference: 0.3244
uv run blindcity compare "results/*.json"                         # summarise what is on disk
```

```bash
uv run blindcity run --mode agent_datahub_live --out results/run.json
```

Every agent run writes a full transcript beside its results — system prompt, the complete
conversation as the model received it, and every reply. Every context bug in this project was
invisible in the scores and obvious in the transcript.

## Commands

One entry point, four subcommands. `blindcity <command> --help` for the full list of flags.

| Command | What it does |
| --- | --- |
| `blindcity sim` | Generate a city's history into the warehouse, or `--serve` the viewer |
| `blindcity emit` | Publish the catalog snapshot to DataHub; `--check` reports differences |
| `blindcity run` | Play one mode of the scenario |
| `blindcity compare` | Summarise result files into one table. Runs nothing |

There is deliberately **no `--repeat`**. Repeats are a shell loop, which needs no feature and keeps
every parameter reachable inside it:

```bash
for i in 1 2 3; do
  for m in agent_raw agent_datahub agent_datahub_live agent_analytics; do
    uv run blindcity run --mode $m --out results/$m-$i.json --overwrite-datahub true
  done
done
uv run blindcity compare "results/*.json" --out docs/comparison.md
```

This used to be a second command (`eval --live --repeat 3`) that re-implemented the runner. It
drifted from the real one three times — no transcripts, no way to clear a stale warehouse, and it
never printed the degradation warnings — so a batch could report a clean table while runs were
losing queries to timeouts. One runner, and a loop.

### DataHub is the authoritative copy

`blindcity run` publishes the catalog before playing, so the metadata the agent reads matches the
commit it is played from and a fresh clone works with no setup. But DataHub is editable, and
widening a band in the UI to see how the agent responds is a thing you are *meant* to be able to
do. So publishing looks before it writes:

```bash
uv run blindcity run --mode agent_datahub_live                          # asks, if anything differs
uv run blindcity run --mode agent_datahub_live --overwrite-datahub true # replace, no question
uv run blindcity run --mode agent_datahub_live --overwrite-datahub false# keep your edits, run on them
```

When DataHub is empty or already matches, the snapshot is published either way — there is nothing
to lose and nothing to ask about. Every run records which copy of the guidance it acted on, and a
fingerprint of it, in `catalog_source` in its `.agent.json`.

See `docs/RESULTS.md` for the full comparison, method and caveats.

## Architecture

```
sim ──rows──────────────>  Postgres  <──read-only SQL──┐
 │                             ▲                       │
 │                             │ per-run views         │
 └──generated lineage───>  DataHub  ──catalog block──>  agent  ──levers──> sim
                              ▲
                              └── assertions, evaluated each turn
```

The simulation emits its own causal graph as DataHub lineage — 29 column-level edges, every one
validated against the running model by `blindcity.sim.causal_check`, so "derived from" states a
demonstrated dependency rather than a claim. Each run gets a private schema of views filtered to its
own `run_id`, with `search_path` pointed at it, so run isolation is structural rather than
remembered.

## Documentation

- `AGENTS.md` — vision, constraints, conventions
- `docs/DECISIONS.md` — why it is built this way
- `docs/ENVIRONMENT.md` — verified setup and running topology
- `docs/ERRORS.md` — every bug that mattered, and what it cost
- `.tasks/mvp/TASKS.md` — current state and what remains

## License

Apache 2.0.
