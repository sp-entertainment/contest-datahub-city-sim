# Results

Seed 42, `gpt-5.6-luna` at reasoning effort `low`, twelve quarterly turns, green threshold 0.62.
The full method is at the end of this page.

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
  and reached green five turns sooner — a gap of the same size as the run-to-run spread, so treat
  it as a direction rather than a magnitude.
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

## `agent_analytics`, and what the catalog is worth to it

DataHub's own Analytics Agent scored 0.6825 in the table above, on a brief that described the
warehouse and the levers and then asked for a decision.

Given an *address* instead — the dataset that carries the operating guidance, and the catalog tool
that fetches it — it goes and gets the guidance through DataHub's own tools and plays on it. On
that brief a run scored **0.8038, green at turn 4**. Every lever sat inside its documented band
from turn 0 to turn 11, and `zoning_release` was never touched: the catalog rates its impact
negligible, and the advisor said so in its own words each turn.

That is the whole claim of this project running end to end with none of our own values in the
prompt: DataHub's catalog steering DataHub's agent, with our side supplying a pointer and nothing
else.

The mode costs an order of magnitude more than ours — around 1.5M tokens against ~200k — because
each of its twelve calls carries a full analysis rather than a single tool step.

## Method

- **Seed 42**, one city, identical for every mode.
- **Twelve quarterly turns**, identical budget for every mode.
- **`gpt-5.6-luna` at reasoning effort `low`** everywhere, including inside the Analytics Agent's
  own service, which `preflight()` verifies at run time.
- **The green threshold is 0.62** on a composite of solvency (0.20), satisfaction (0.30), service
  (0.30) and population retention (0.20).
- **One run per mode** in the table above. The modes are stochastic and measured run-to-run spread
  on identical repeats reaches 0.08 of final index, so `blindcity compare` prints the spread beside
  every mean and flags any gap smaller than it. Read the ordering, and read gaps larger than the
  spread.
- **Every run started from an empty warehouse** and published the catalog from the commit's own
  snapshot before playing.

## Run health

Every run in the table was clean: **zero infrastructure failures, zero timeouts**, and 0–1
recoverable bad-column errors. All modes published the catalog from the snapshot before playing,
and every agent mode confirmed `reasoning_effort=low` was accepted by the provider rather than
silently dropped.
