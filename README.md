# Blind City

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

Three runs per mode, `gpt-5.6-luna` at reasoning effort `low`.

| Mode | What the catalog provides | Mean index | Green by turn | SQL queries |
| --- | --- | ---: | ---: | ---: |
| `agent_raw` | Nothing. Schema discovery via `information_schema` only | 0.7151 | 6, 7, 7 | 65 |
| `agent_datahub` | Descriptions, glossary, column-level lineage | 0.7378 | 5, 5, 5 | 59 |
| `agent_datahub_live` | The above, plus expert assertions evaluated each turn | **0.8129** | **4, 3, 4** | **13** |
| `agent_analytics` | DataHub's own Analytics Agent answers instead | 0.6965 | 6, 4, 5 | — |
| *`GOOD_POLICY`* | *hand-calibrated reference, not an agent* | *0.8132* | *4* | *—* |
| *`BAD_POLICY`* | *deliberate neglect, not an agent* | *0.3244* | *never* | *—* |

Green is 0.62. **The fully-catalogued agent matched the hand-tuned expert policy, got there
faster, and used a fifth of the queries to do it.**

Read the green turn rather than the mean index — it is the cleaner signal. The three ranges do not
overlap: every catalogued run reached green at least as fast as the fastest uncatalogued one, and
every assertion-guided run beat every catalogued one. The mean index has run-to-run spread of
0.0824, which is larger than the `agent_raw`/`agent_datahub` gap, and the comparison tool says so
itself rather than leaving it to be noticed.

### What we actually learned

The interesting result is not "catalogs help." It is *which kind* of metadata helped:

- **Descriptive metadata alone was worth little.** `agent_datahub` beats `agent_raw` by 0.0227 of
  final index — inside the noise. Across earlier paired runs that gap ran +0.045, +0.043 and
  **−0.040**; the sign flipped, and a quantity that changes sign across runs is not measuring what
  it claims to. It does reach green two turns earlier in all three runs, so the effect is probably
  real, but it is small and this many repeats cannot size it. Our table names are already
  human-readable, so a description that says `income_tax_revenue: Income tax collected` adds
  nothing the column name did not.
- **Prescriptive metadata transformed behaviour.** Assertions that document the operating range a
  healthy city holds to — and, just as importantly, which levers are *not worth tuning* — moved the
  agent from muddling through to expert play — and, tellingly, on *less* of everything: a fifth of
  the queries, 19 LLM calls against 27, and green three turns sooner. A mode that scored higher by
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
  catalog is built and emitted by `uv run datahub-emit --baseline`, but the agent modes query the
  real warehouse with its readable names, so the handicap was never applied. This is very likely why
  descriptive metadata showed no measurable effect.
- **One seed.** Three runs per mode, but all on seed 42. The spread across those three reaches
  0.0824 of final index, which is larger than the `agent_datahub`/`agent_raw` gap — so that gap
  is unresolved, and the table says so. The `agent_datahub_live` margin and the green-turn
  ordering are both outside the noise.
- **`agent_analytics` is a floor, not a measurement.** DataHub's own Analytics Agent reported "No
  governed definitions ... were found in DataHub" on every run and answered from the warehouse
  alone. Its score is where an *uncatalogued* analyst lands, which is within noise of
  `agent_raw`, and it is not evidence about the agent's ceiling.
- **The `human` mode has not been played end to end.** The lever panel and scene work.

## Quick start

Requires 16 GB RAM, 25 GB disk, Docker, Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
datahub docker quickstart          # DataHub Core on :9002, GraphQL on :8080
docker compose -f infra/postgres/docker-compose.yml up -d   # warehouse Postgres on :5432
uv sync --group dev
```

```bash
uv run sim --seed 42 --years 20    # generate a city into the warehouse
uv run datahub-emit                # schemas, descriptions, glossary, lineage, assertions
uv run sim --serve                 # viewer and lever panel on :8000
```

```bash
uv run eval --dry-run              # verify the whole harness, free
```

```bash
uv run agent --mode agent_datahub_live --out results/run.json
```

Every agent run writes a full transcript beside its results — system prompt, the complete
conversation as the model received it, and every reply. Every context bug in this project was
invisible in the scores and obvious in the transcript.

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

- `docs/RESULTS.md` — the full comparison, method, and caveats
- `AGENTS.md` — vision, constraints, conventions
- `docs/DECISIONS.md` — why it is built this way
- `docs/ENVIRONMENT.md` — verified setup and running topology
- `docs/ERRORS.md` — every bug that mattered, and what it cost
- `.tasks/mvp/TASKS.md` — current state and what remains

## License

Apache 2.0.
