# Devpost submission draft

Copy-paste material for the submission form. Human-owned tasks (H2 public repo, H4 video,
H5 submit) are tracked in `.tasks/mvp/TASKS.md`.

---

## Elevator pitch (200 chars)

A city simulation with no interface. An agent must fix a crisis using only SQL and DataHub. Three
catalog levels, measured — and the answer to "does metadata help?" is not the one we expected.

---

## Inspiration

Every game interface does two jobs: it finds the relevant numbers among everything the engine
tracks, and it explains what they mean. That is exactly what a metadata catalog does for a data
warehouse.

So we removed the interface. The city runs, it writes hundreds of thousands of rows to Postgres, and
the player sees only the city and eight levers — no charts, no counters, no warnings. To find out
what is happening, you query the warehouse. And if a catalog really does what an interface does, an
agent with a good one should play better than an agent without.

That turned out to be a testable claim, which made it a benchmark rather than a game.

## What it does

**Blind City is a benchmark for whether data catalogs make AI agents better at their job.**

A simulation puts a city through five years of deferred maintenance plus a fiscal shock. An agent
gets twelve quarterly decisions and eight policy levers to bring a composite health index — solvency,
satisfaction, service, population retention — back into the green.

The agent cannot see the city. It queries the warehouse. What varies between modes is only how much
DataHub tells it about that warehouse:

| Mode | Catalog | Final index | Green by |
| --- | --- | ---: | ---: |
| `agent_raw` | none | 0.6837 | turn 7 |
| `agent_datahub` | descriptions, glossary, column-level lineage | 0.7362 | turn 6 |
| `agent_datahub_live` | plus expert assertions, evaluated each turn | **0.8147** | **turn 3** |

Green is 0.62. A hand-calibrated expert policy scores 0.8132 and reaches green at turn 4 — the fully
catalogued agent beat it, in fewer turns, using half the SQL queries of the weakest mode.

## What we learned

The interesting result is not "catalogs help." It is *which kind* of metadata helped.

**Descriptive metadata alone did not measurably help.** Across four paired runs the gap between
`agent_raw` and `agent_datahub` was +0.045, +0.043, **−0.040**, +0.053. The sign flipped. Our tables
have readable names, so a description reading `income_tax_revenue: Income tax collected` tells an
agent nothing the column name did not — and 37 of our 123 column descriptions were exactly that
tautological.

**Prescriptive metadata transformed behaviour.** Assertions documenting the operating range a
healthy city holds to, the measured impact of each lever, and — just as importantly — which levers
are *not worth tuning*, moved the agent from muddling through to expert play.

**Lineage matters most where the data cannot speak.** Every lever is constant across the entire
recorded history, so no amount of querying reveals that `income_tax_rate` drives
`income_tax_revenue`. The catalog is the only place that relationship exists.

There is a sharper version of this. Before assertions, in *every run of every mode*, no agent ever
changed the income tax rate — while all of them fixed the roads. Roads announce themselves
(`wear = 0.97`); a starved tax rate looks like a policy choice. Solvency ended between 0.042 and
0.467 every time. With assertions it reached 0.829.

For a data platform team, the practical reading: documenting your columns will not make your
warehouse agent-ready. Documenting what *good* looks like might.

## How we built it

- **Simulation** in pure Python, seeded and deterministic, ~820k rows for a 20-year run.
- **Warehouse** on PostgreSQL 16. Each benchmark run gets a private schema of views filtered to its
  own `run_id`, with `search_path` pointed at it, so run isolation is structural rather than
  remembered.
- **DataHub Core** via the OSS quickstart. Schemas, descriptions, a 20-term business glossary,
  assertions, and 29 column-level lineage edges — all emitted by `uv run blindcity emit`.
- **The lineage is generated from the simulation's own causal graph**, and every edge is validated
  against the running model: `blindcity.sim.causal_check` perturbs each source, runs the code that
  computes the target, and requires the target to move. "Derived from" states a demonstrated
  dependency, not a claim.
- **The agent** is one class instantiated three times. There is no `if mode ==` anywhere in the loop;
  the build fails if the three modes' prompts, tools or turn messages differ by anything other than
  the catalog block.

## Challenges

**Four bugs silently corrupted results while every test passed.** Each is worth naming because each
produced plausible numbers:

- The agent could not see the consequences of its own decisions. The warehouse writer batched at
  5,000 rows, so `ticks` (one row a month) stayed frozen at the last month of the crisis for entire
  runs while `citizen_monthly` trickled through. `max(tick)` never moved and cross-table joins were
  misaligned by months. Fixing it was worth +0.06 on its own.
- The glossary was emitted to DataHub and never linked to any dataset, so the catalog promised
  "business glossary definitions" and delivered none — invisible in every report.
- Each turn opened on a blank conversation, so the agent re-ran `information_schema` 29 times and
  issued the same fatal query on four separate turns.
- A run that lost four queries to timeouts printed `0 errors`.

The fix that mattered most was not any single patch: it was recording the full transcript of every
exchange. Every one of these was invisible in the scores and obvious in the transcript.

**Our own assertions were wrong twice, and validation caught both.** A satisfaction *trend* detector
was exactly backwards — in a collapsing city satisfaction rises, because neglect drives a third of
the population out and the survivors get shorter commutes. And `transit_fare` was labelled "low
yield" when it moves the outcome 2.8%.

## What's next

- Apply the opaque-name control catalog to `agent_raw`. It is built and emitted but was never wired
  to the agent modes, which is very likely why descriptive metadata showed no effect.
- More seeds. The assertion result is far outside the observed 0.02 run-to-run variance; the
  descriptive-metadata result is not.
- Finish the `human` mode by wiring the upstream DataHub Analytics Agent, for a human baseline.

## Built with

`python` · `postgresql` · `datahub` · `openai` · `fastapi` · `docker` · `uv` · `psycopg`
