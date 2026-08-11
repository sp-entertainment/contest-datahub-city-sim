# Results

Seed 42, `gpt-5.6-luna` at reasoning effort `low`, twelve quarterly turns, green threshold 0.62.
**Three runs per agent mode.** The full method is at the end of this page.

Every number came from a run whose full transcript is in `results/official/`: the system prompt, the
complete conversation as the model received it, and every reply. Reproduce the whole table with

```bash
uv run blindcity compare "results/official/*.json"
```

## Headline

Mean of three runs per agent mode. The scripted policies are deterministic and run once.

| Mode | What the catalog gives it | Index | Spread | Green by | Tokens | SQL |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | Nothing but `information_schema` | 0.6416 | 0.0238 | 9, 7, 9 | 179,499 | 64 |
| `agent_datahub` | Descriptions, glossary, column lineage | 0.7413 | 0.0710 | 6, 5, 6 | 221,770 | 52 |
| `agent_datahub_live` | The above, plus assertions read from DataHub each turn | **0.8092** | 0.0175 | **3, 4, 3** | 177,444 | **16** |
| `agent_analytics` | DataHub's own Analytics Agent answers instead | 0.8017 | 0.0554 | 4, 3, 4 | 1,456,443 | — |
| *`good_policy`* | *hand-calibrated reference, not an agent* | *0.8132* | — | *4* | *0* | *0* |
| *`bad_policy`* | *deliberate neglect, not an agent* | *0.3244* | — | *never* | *0* | *0* |

Every agent run recovered: 12 of 12 crossed green inside the budget.

**The predicted ordering held on the means and on all three paired rounds**, not just on average:

| Round | `agent_raw` | `agent_datahub` | `agent_datahub_live` |
| --- | ---: | ---: | ---: |
| 1 | 0.6568 | 0.7135 | 0.8092 |
| 2 | 0.6330 | 0.7846 | 0.8004 |
| 3 | 0.6349 | 0.7259 | 0.8179 |

## Both catalog steps clear the noise

With one run per mode this table could only report a direction. With three it can compare ranges,
and **neither pair overlaps**:

| Step | Range below | Range above | Gap between means |
| --- | --- | --- | ---: |
| Descriptions, glossary, lineage | 0.6330 – 0.6568 | 0.7135 – 0.7846 | **0.0997** |
| Assertions, read live from DataHub | 0.7135 – 0.7846 | 0.8004 – 0.8179 | **0.0679** |

Descriptive metadata is the larger of the two steps here, and its arms are cleanly separated: the
best uncatalogued run scored below the worst catalogued one. Prescriptive metadata adds a second
step of similar size on top, and does it from a base that is already good.

The two behave differently in a way the means hide. `agent_datahub` is the *least* consistent mode
in the table — 0.0710 of spread, three times `agent_datahub_live`'s 0.0175. Descriptions tell the
agent what a column means and leave it to decide what to do; assertions tell it what good looks
like, and the runs converge.

## The queries are the finding

`agent_datahub_live` scored highest on **less of everything**:

| Mode | Index | SQL queries | Model calls | Tokens | Wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | 0.6416 | 64 | 28 | 179,499 | 114 |
| `agent_datahub` | 0.7413 | 52 | 25 | 221,770 | 92 |
| `agent_datahub_live` | **0.8092** | **16** | **17** | **177,444** | **62** |

A quarter of the queries, and fewer tokens than the uncatalogued control. That shape is hard to get
by accident: a mode that scored higher by querying *more* would just be a mode given more compute.
This one stopped searching, because the catalog told it where the problem was and which levers were
worth moving.

## Health components, mean of the final turn

| Mode | Solvency | Satisfaction | Service | Population |
| --- | ---: | ---: | ---: | ---: |
| `agent_raw` | 0.524 | 0.575 | 0.756 | 0.687 |
| `agent_datahub` | 0.744 | 0.728 | 0.736 | 0.767 |
| `agent_datahub_live` | 0.791 | **0.807** | **0.832** | 0.798 |
| `agent_analytics` | 0.810 | 0.779 | 0.828 | 0.787 |
| *`good_policy`* | *0.976* | *0.734* | *0.792* | *0.800* |
| *`bad_policy`* | *0.540* | *0.263* | *0.260* | *0.297* |

This is where the comparison against the hand-calibrated reference gets interesting. `good_policy`
edges the catalogued agent on the composite index (0.8132 against 0.8092) and gets there almost
entirely on solvency — 0.976, a treasury far larger than the city needs. `agent_datahub_live` beats
it on satisfaction and on service, reaches green a turn earlier, and leaves a more balanced city
behind. A city can be made solvent by taxing until the residents leave; the index is a composite
precisely so that trade shows up.

## The assertions come out of DataHub, not our prompt

The operating guidance is published to DataHub and read back from GMS at run start.
`agent_datahub_live` imports none of it, and a test asserts that structurally. All three runs
recorded the fingerprint of the guidance they actually played on, and all three match:

```
catalog_source: {"applied": true, "source": "snapshot",
                 "guidance_fingerprint": "sha256:5cf1a9bd53faa1f6",
                 "levers": 8, "outcomes": 5, "lags": 4}
```

Edit a band in the DataHub UI, run with `--overwrite-datahub false`, and the next run plays
differently with no code change — the fingerprint in its report will differ, so the two runs cannot
be confused.

## DataHub's own agent, given only an address

`agent_analytics` scored **0.8017**, which is 0.0075 from `agent_datahub_live` — inside the noise,
so the two are not distinguishable at three runs each. Its brief names the dataset that carries the
operating guidance and the catalog tool that fetches it, and nothing else; it goes and gets the
guidance through DataHub's own tools and plays on what it finds.

**It read the guidance on 12 of 12 turns, in all three runs.** `zoning_release` was never touched:
the catalog rates its impact negligible, and the advisor said so in its own words.

That is the project's claim closing end to end with none of our own values in the prompt — DataHub's
catalog steering DataHub's agent, with our side supplying a pointer.

It is the expensive way to get there. 1,456,443 tokens against `agent_datahub_live`'s 177,444, and
539 wall seconds against 62, because each of its twelve calls carries a full analysis rather than a
single tool step.

## Run health

All fourteen runs were clean:

- **Zero lost turns.** Every run played all twelve.
- **Zero timeouts and zero infrastructure failures.**
- **Every agent mode ran `gpt-5.6-luna` at reasoning effort `low`**, confirmed accepted by the
  provider rather than silently dropped, and `preflight()` verified the same model inside the
  Analytics Agent's own service before scoring it.
- `agent_analytics` hit provider rate limits eleven times across its three runs and recovered from
  every one — the backoff waits out the full token window rather than losing the turn.
- Both scripted references reproduced their previously recorded values exactly (0.8132 and 0.3244),
  confirming the simulation and the index are unchanged.

## Method

- **Seed 42**, one city, identical for every mode.
- **Twelve quarterly turns**, identical budget for every mode.
- **Three runs per agent mode**, reported as a mean with the observed spread beside it.
  `blindcity compare` prints the spread from the data and flags any gap between modes smaller than
  it — the `agent_datahub_live` / `agent_analytics` gap is flagged, and the two catalog steps
  are not.
- **`gpt-5.6-luna` at reasoning effort `low`** everywhere, including inside the Analytics Agent's
  own service.
- **The green threshold is 0.62** on a composite of solvency (0.20), satisfaction (0.30), service
  (0.30) and population retention (0.20).
- **Every run started from an empty warehouse** and published the catalog from the commit's own
  snapshot before playing.
- **No mode was told the scoring function**, and no city-state number appears in any prompt.
