# Devpost submission

Copy-paste material for the submission form.

---

## Elevator pitch (200 chars)

A city simulation with no interface. An agent must fix a crisis using only SQL and DataHub. Four
catalog levels, measured — and the answer to "does metadata help?" is not the obvious one.

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

**City Sim Agent Benchmark is a benchmark for whether data catalogs make AI agents better at their
job.**

A simulation puts a city through five years of deferred maintenance plus a fiscal shock. An agent
gets twelve quarterly decisions and eight policy levers to bring a composite health index —
solvency, satisfaction, service, population retention — back into the green.

The agent cannot see the city. It queries the warehouse. What varies between modes is only how much
DataHub tells it about that warehouse:

| Mode | Catalog | Final index | Green by |
| --- | --- | ---: | ---: |
| `agent_raw` | none | 0.6488 | turn 10 |
| `agent_datahub` | descriptions, glossary, column-level lineage | 0.7187 | turn 5 |
| `agent_datahub_live` | plus expert assertions, read from DataHub each turn | **0.8187** | **turn 3** |
| `agent_analytics` | DataHub's own Analytics Agent answers instead | 0.6825 | turn 5 |

Green is 0.62. A hand-calibrated expert policy scores 0.8132 and reaches green at turn 4 — the fully
catalogued agent beat it, in fewer turns, using a third of the SQL queries the uncatalogued mode
needed.

## What we learned

The interesting result is not "catalogs help." It is *which kind* of metadata helped.

**Descriptive metadata alone did not measurably help.** Our tables have readable names, so a
description reading `income_tax_revenue: Income tax collected` tells an agent nothing the column
name did not.

**Prescriptive metadata transformed behaviour.** Assertions documenting the operating range a
healthy city holds to, the measured impact of each lever, and — just as importantly — which levers
are *not worth tuning*, moved the agent from muddling through to expert play. It did it on **less**
of everything: 22 queries against 62, 19 model calls against 30.

**Lineage matters most where the data cannot speak.** Every lever is constant across the entire
recorded history, so no amount of querying reveals that `income_tax_rate` drives
`income_tax_revenue`. The catalog is the only place that relationship exists.

There is a sharper version of this. Before assertions, in *every run of every mode*, no agent ever
changed the income tax rate — while all of them fixed the roads. Roads announce themselves
(`wear = 0.97`); a starved tax rate looks like a policy choice. Solvency ended between 0.042 and
0.467 every time. With assertions it reached 0.829.

For a data platform team, the practical reading: documenting your columns will not make your
warehouse agent-ready. Documenting what *good* looks like will.

## How we built it

- **Simulation** in pure Python, seeded and deterministic, ~820k rows for a 20-year run.
- **Warehouse** on PostgreSQL 16. Each benchmark run gets a private schema of views filtered to its
  own `run_id`, with `search_path` pointed at it, so run isolation is structural rather than
  remembered.
- **DataHub Core** via the OSS quickstart. Schemas, descriptions, a 20-term business glossary,
  assertions, per-lever operating guidance, and 29 column-level lineage edges — all published by
  `uv run blindcity emit`, and all read back out of DataHub at run time.
- **The lineage is generated from the simulation's own causal graph**, and every edge is validated
  against the running model: `blindcity.sim.causal_check` perturbs each source, runs the code that
  computes the target, and requires the target to move. "Derived from" states a demonstrated
  dependency, not a claim.
- **The agent** is one class instantiated three times. There is no `if mode ==` anywhere in the
  loop; the build fails if the three modes' prompts, tools or turn messages differ by anything
  other than the catalog block.
- **A fourth mode runs DataHub's own Analytics Agent** as a separate service, given a pointer to
  the guidance in the catalog and left to fetch it with its own tools.

## Challenges we ran into

**In a benchmark, a broken measurement produces plausible numbers.** A run with a corrupted context
does not crash — it scores 0.68 and looks like a result. Every test can be green while an agent is
quietly reading a frozen table, or answering with a catalog connection that silently loaded zero
tools.

So the project is built around making that visible:

- **Every agent run records its full transcript** — the system prompt, the conversation exactly as
  the model received it, and every reply. Every context bug this project had was invisible in the
  scores and obvious in the transcript.
- **Assertions are re-derived from the simulation** by the test suite, which fails if a documented
  band stops matching what the code does. This caught two of our own assertions being wrong: a
  satisfaction *trend* detector that was exactly backwards — in a collapsing city satisfaction
  rises, because neglect drives a third of the population out and the survivors get shorter
  commutes — and `transit_fare` labelled "low yield" when it moves the outcome 2.8%.
- **Every run records a fingerprint of the guidance it played on**, so two runs on different
  catalog states can never be confused for repeats.
- **The comparison reports its own limits** — run-to-run spread beside every mean, and a warning
  when a gap between modes is smaller than that spread.

## Contributed upstream

[**datahub-project/analytics-agent#97**](https://github.com/datahub-project/analytics-agent/pull/97)
— *support OpenAI reasoning models via the Responses API.* The Analytics Agent built its OpenAI
client with no way to set the reasoning budget, so it always called `/v1/chat/completions`, where
the `gpt-5.6-*` family refuses function tools unless reasoning is switched off entirely. The change
adds an `OPENAI_REASONING_EFFORT` setting that routes through `/v1/responses` and passes the effort
down, in one factory that all four of the agent's model tiers already share.

## What's next

- More seeds and more repeats, to size the descriptive-metadata effect rather than just its sign.
- A `human` baseline played end to end through the viewer and the Analytics Agent.
- Seed the simulation from real historical city data, so the benchmark runs against real conditions.

## Built with

`python` · `postgresql` · `datahub` · `openai` · `fastapi` · `docker` · `uv` · `psycopg`
