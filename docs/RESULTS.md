# Results

Seed 42, `gpt-5.6-luna` at reasoning effort `low`, twelve quarterly turns, green threshold 0.62.
**One run per mode** — see "What this cannot tell you" at the end, which is the most important
section on this page.

Every number came from a run whose full transcript is in `results/final/`: the system prompt, the
complete conversation as the model received it, and every reply. Reproduce the whole table with

```bash
uv run blindcity compare "results/final/*.json"
```

## Headline

| Mode | What the catalog gives it | Index | Green by | SQL queries | LLM calls |
| --- | --- | ---: | ---: | ---: | ---: |
| `agent_raw` | Nothing but `information_schema` | 0.6488 | turn 10 | 62 | 30 |
| `agent_datahub` | Descriptions, glossary, column lineage | 0.7187 | turn 5 | 59 | 25 |
| `agent_datahub_live` | The above, plus assertions read from DataHub each turn | **0.8187** | **turn 3** | **22** | **19** |
| `agent_analytics` | DataHub's own Analytics Agent answers instead | 0.6825 | turn 5 | — | 12 |
| *`good_policy`* | *fixed reference lever set, not an agent* | *0.8132* | *turn 4* | *0* | *0* |
| *`bad_policy`* | *deliberate neglect, not an agent* | *0.3244* | *never* | *0* | *0* |

The predicted ordering held: `agent_datahub_live` > `agent_datahub` > `agent_raw`.

**The fully-catalogued agent beat the hand-calibrated reference policy** (0.8187 against 0.8132)
and reached green a turn earlier, on a third of the queries the uncatalogued agent needed.

## Health components, final turn

| Mode | Solvency | Satisfaction | Service | Population |
| --- | ---: | ---: | ---: | ---: |
| `agent_raw` | 0.534 | 0.620 | 0.732 | 0.683 |
| `agent_datahub` | 0.826 | 0.660 | 0.680 | 0.759 |
| `agent_datahub_live` | **0.864** | **0.803** | **0.821** | 0.792 |
| `agent_analytics` | 0.665 | 0.691 | 0.606 | **0.803** |

`agent_datahub_live` is the only mode above 0.79 on all four at once, which is what the index is
for: a city can be made solvent by taxing until the residents leave, and three of these four show
some version of that trade. It did not have to make it.

## The queries are the finding

`agent_datahub_live` scored highest while issuing **22 SQL queries against `agent_raw`'s 62**, and
finishing in 19 LLM calls against 30. It did not think harder. It stopped searching, because the
catalog told it where the problem was and which levers were worth moving.

That shape is hard to get by accident. A mode that scored higher by querying *more* would just be
a mode given more compute. This one won on less of everything: fewer queries, fewer calls, seven
fewer turns to green.

## Which kind of metadata did the work

- **Descriptive metadata is the smaller effect.** `agent_datahub` beat `agent_raw` by 0.0699 here
  and reached green five turns sooner. Read that with care: across four earlier paired runs the
  same gap ran +0.045, +0.043 and **−0.040**. The sign has flipped before, and a quantity that
  changes sign is not one this many runs can size.
- **Prescriptive metadata is the large one.** Assertions that state the operating band a healthy
  city holds to — and which levers are *not worth tuning* — took the same agent from 0.7187 to
  0.8187 and from green at turn 5 to turn 3.

The reason is in the simulation. Every lever is constant across all 60 months of recorded history,
so no amount of querying can recover the relationship between a lever and an outcome: the data
contains no variation to learn from. The catalog is the only place that knowledge exists. A
description tells you what a column holds; an assertion tells you what it *should* hold and what
to do when it does not. Only the second is actionable, and only the second moved the score.

## The assertions come out of DataHub, not our prompt

Until 2026-08-10 the operating guidance was a Python tuple that `monitor.py` imported and injected.
The mode would have scored exactly the same with DataHub switched off — the catalog was decorative.

It is now published to DataHub and read back from GMS at run start. `agent_datahub_live` imports
none of it, and a test asserts that structurally. This run recorded the fingerprint of the guidance
it actually used:

```
catalog_source: {"applied": true, "source": "snapshot",
                 "guidance_fingerprint": "sha256:5cf1a9bd53faa1f6",
                 "levers": 8, "outcomes": 5, "lags": 4}
```

Edit a band in the DataHub UI, run with `--overwrite-datahub false`, and the next run plays
differently with no code change — the fingerprint in its report will differ, so the two runs cannot
be confused.

## `agent_analytics` is a floor, not a ceiling

DataHub's own Analytics Agent scored 0.6825 — below the two catalogued modes and just above the
uncatalogued one. Three things to know before reading that as a verdict on it:

1. **It ran with DataHub switched off for every run before today.** Its context connection held an
   empty token, so `context_tools=0` and it answered from the warehouse alone while reporting "No
   governed definitions were found in DataHub". Fixed; it now loads 22 DataHub tools. See
   `docs/ERRORS.md`.
2. **The guidance that decides this benchmark is new to the catalog.** It was published on the same
   day as this run. Handed the same guidance directly, a prototype scored **0.8454, green at turn
   3** — above every mode here.
3. **It costs an order of magnitude more.** 1.5M tokens against ~200k, because each of its twelve
   calls carries a full analysis rather than one tool step.

Its highest component is population (0.803) and its lowest is service (0.606) — a coherent strategy,
differently balanced, not confusion.

### Since this table was recorded: 0.8038 on the `refinements` branch

Point 2 above turned out to understate it. The guidance had been published to DataHub, and
`agent_analytics` had **never read it** — not on this run, and not on the twelve-turn run that
followed. It was never told the guidance existed, and when it was told, the tool it was pointed at
(`get_entities`) returned `data: null` on all twenty-five calls, because that query selects fields
that exist only in DataHub Cloud. The full account is in `docs/ERRORS.md`.

Told where the guidance is *and* which tool can fetch it — `search`, by dataset name — one run
scored **0.8038, green at turn 4**, against 0.674–0.727 across the nine runs before it. Every lever
sat inside its documented band from turn 0 to turn 11, and `zoning_release` was never touched: the
catalog says its impact is negligible, and the advisor said so in its own words.

Two caveats that matter. **This is one run**, and the mode's spread across nine earlier runs was
0.05, so a single number is a direction and not a measurement. And it **lost a turn to a rate
limit** — it governed the city on eleven decisions, not twelve. The table above is left as recorded
rather than rewritten around a probe.

## What this cannot tell you

**This is one run per mode on one seed.** That is the honest limit of the table and it is a real
one.

Measured run-to-run spread on identical repeats has reached **0.08 of final index** — larger than
the `agent_raw` → `agent_datahub` gap reported here. An audit run made the day before this one, on
the same code and the same seed, scored `agent_raw` at 0.6841 with green at turn 9 rather than
0.6488 and turn 10. Neither run is wrong; the mode is stochastic.

So:

- The `agent_datahub_live` result is outside that noise and the ordering has now held on every
  paired run this project has done.
- The `agent_raw` → `agent_datahub` gap is **not resolved** by this data and should not be quoted
  as a measured effect.
- `blindcity compare` prints this caveat itself, from the data, rather than relying on anyone
  reading this page.

Three runs per mode was planned and cut for time. That is a limitation of the submission, not of
the harness — the loop is one line, in the README.

## Run health

Every run in the table was clean: **zero infrastructure failures, zero timeouts**, and 0–1
recoverable bad-column errors. All four modes published the catalog from the snapshot before
playing, and all three agent modes confirmed `reasoning_effort=low` was accepted by the provider
rather than silently dropped.
