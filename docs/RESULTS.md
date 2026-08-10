# Results

Every number here came from a run whose full transcript is in `results/eval-luna/`. The system
prompt, the complete conversation as the model received it, and every reply are recorded, so any
claim below can be checked against what the agent actually saw.

Seed 42, `gpt-5.6-luna` at reasoning effort `low`, twelve quarterly turns, green threshold 0.62.
**Three runs per mode**, because one run per mode is not a measurement.

## Headline

| Mode | Mean index | Range | Green by turn | Solvency | Satisfaction | Service | Population |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | 0.7151 | 0.7016–0.7306 | 6, 7, 7 | 0.766 | 0.663 | 0.728 | 0.723 |
| `agent_datahub` | 0.7378 | 0.7307–0.7489 | 5, 5, 5 | 0.749 | 0.721 | 0.712 | 0.790 |
| `agent_datahub_live` | **0.8129** | 0.7698–0.8522 | **4, 3, 4** | 0.776 | 0.805 | 0.833 | 0.832 |
| `agent_analytics` | 0.6965 | 0.6848–0.7025 | 6, 4, 5 | 0.845 | 0.575 | 0.710 | 0.710 |
| *`GOOD_POLICY`* | *0.8132* | *—* | *4* | *0.976* | *0.734* | *0.792* | *0.800* |
| *`BAD_POLICY`* | *0.3244* | *—* | *never* | *0.540* | *0.263* | *0.260* | *0.297* |

`GOOD_POLICY` and `BAD_POLICY` are fixed scripted lever sets, not agents. They bracket the scenario
and show it is both winnable and losable. Every mode recovered in all three runs, so the scenario
does not separate them on *whether* the city is saved — it separates them on how fast, and at what
cost.

## Read the green turn, not the mean index

The mean index is the noisier statistic, and it understates the result. Run-to-run spread reaches
0.0824, which is larger than the 0.0227 gap between `agent_raw` and `agent_datahub` — the
comparison tool says so itself, in the generated `comparison.md`, rather than leaving it to be
noticed.

The turn each mode first reached green does separate them, cleanly and without overlap:

```
agent_raw          6, 7, 7
agent_datahub      5, 5, 5
agent_datahub_live 4, 3, 4
```

Three ranges, no shared value between adjacent modes. Every catalogued run reached green at least
as fast as the fastest uncatalogued one, and every assertion-guided run beat every catalogued one.
That is the ordering the benchmark predicted, holding across every repeat rather than on average.

## The queries are the finding

| Mode | Tokens (mean) | LLM calls | SQL queries per run |
| --- | ---: | ---: | ---: |
| `agent_raw` | 177,287 | 27 | 65, 67, 64 |
| `agent_datahub` | 232,114 | 26 | 62, 61, 54 |
| `agent_datahub_live` | 201,490 | 19 | **10, 17, 13** |
| `agent_analytics` | 603,624 | 12 | — (queries run inside the advisor) |

`agent_datahub_live` reached green fastest while issuing roughly **a fifth** of the queries, and
finishing in 19 LLM calls against 27. It was not searching. It was told where the problem was and
went there.

This is the part of the result that is hard to get by accident. A mode that scored higher by
querying *more* would just be a mode that got more compute. This one scored higher on less of
everything: fewer queries, fewer calls, fewer turns to green. The catalog did not help it think
harder; it removed the need to.

## Descriptive metadata alone did not move the needle

`agent_datahub` gets the catalog — table and column descriptions, glossary terms, lineage — and
beats `agent_raw` by 0.0227 of final index, which is inside the noise. It does reach green two
turns earlier and does so in all three runs, so the effect is probably real, but the honest
statement is that **description alone is a small effect and this many repeats cannot size it.**

Across the project's history that gap has run +0.045, +0.043, −0.040 and +0.053. The sign flipped.
A metric that changes sign across runs is not measuring what it claims to.

`agent_datahub_live` adds assertions evaluated against the live city each turn — the same catalog,
plus a statement of which values are out of band and which levers are worth touching. That is
where the effect appears, and it is the largest in the table.

The reason is in the simulation. Every lever is constant across all 60 months of history, so no
amount of querying can recover a causal relationship between a lever and an outcome: the data
contains no variation to learn from. The catalog is the only place that knowledge exists. A
description of a column tells you what it holds; an assertion tells you what it should hold and
what to do when it does not. Only the second is actionable, and only the second moved the score.

## The Analytics Agent is a floor, not a measurement

`agent_analytics` delegates the whole analysis to DataHub's own Analytics Agent. It scored 0.6965,
below every mode we wrote — but that number should not be read as "DataHub's agent is worse".

It reported *"No governed definitions or table-selection guidance were found in DataHub"* on every
run, and `context_tools=0` in its own logs. Its DataHub context lookup reaches GMS and does not
find our metadata, so it answered from the warehouse alone. It is, in other words, an
**uncatalogued** analyst — and it landed within noise of `agent_raw` (0.6965 vs 0.7151), which is
exactly where an uncatalogued analyst should land.

Its cost profile is different in kind: 603,624 tokens against 177,287, in 12 calls instead of 27,
because each call carries a full analysis rather than a single tool step. It also has no memory of
the city between turns beyond what the question carries.

Its solvency is the highest of any mode at 0.845 and its satisfaction the lowest at 0.575 — it
taxed and charged its way to a balanced budget and the residents left. That is a coherent strategy
badly calibrated, not confusion.

## What was fixed to make these numbers trustworthy

Four things were wrong before this run, all found by looking rather than by a failing test:

- **The advisor had no query timeout.** It connects with its own engine, so our 45s cap never
  applied — an unlimited query budget against arms that have one. One aggregate ran 21 minutes,
  outlived the run, and blocked the next run's warehouse reset on a lock.
- **Only the advisor's main tier model was pinned.** Chart, quality and delight defaulted to
  `gpt-4o-mini`, which rejects `reasoning.effort`; the quality tier returned 400 and context
  assessment was silently skipped. `preflight()` only sees the main model, so this is a mismatch
  the fairness guard structurally cannot catch.
- **`uv run eval --live` wrote no transcripts.** The path producing the submission's numbers was
  the only unauditable way to produce a score.
- **The transcript wrapper hid the reasoning budget.** `RecordingLLM` proxied `model` and nothing
  else, so `reasoning_effort` and `reasoning_sent` read `None` in every report that recorded a
  transcript. The budget was applied correctly and the audit trail said "unknown".

Every run in this table is clean: **zero infrastructure failures, zero timeouts, and 0–1
bad-table-or-column errors per run** across all twelve.

## Not comparable with anything from gpt-4o

An earlier attempt put every mode on `gpt-4o`. It was abandoned: `agent_raw` lost turns 8–11 to a
30,000 TPM refusal and made 28 bad-table-or-column errors in the turns it did play, against 0–1
here. Those numbers are discarded, not reconciled. See `docs/DECISIONS.md`, 2026-08-10.
