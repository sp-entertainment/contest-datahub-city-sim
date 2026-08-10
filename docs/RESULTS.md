# Results

Every number here came from a run whose full transcript is in `results/`. The system prompt, the
complete conversation as the model received it, and every reply are recorded, so any claim below
can be checked against what the agent actually saw.

## Headline

Seed 42, `gpt-5.6-luna`, twelve quarterly turns, green threshold 0.62. One run per mode.

| Mode | Final index | Green by | Solvency | Satisfaction | Service | Population |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | 0.6837 | turn 7 | 0.585 | 0.723 | 0.671 | 0.743 |
| `agent_datahub` | 0.7362 | turn 6 | 0.734 | 0.703 | 0.744 | 0.776 |
| `agent_datahub_live` | **0.8147** | **turn 3** | 0.829 | 0.810 | 0.820 | 0.799 |
| *`GOOD_POLICY`* | *0.8132* | *turn 4* | *0.976* | *0.734* | *0.792* | *0.800* |
| *`BAD_POLICY`* | *0.3244* | *never* | *0.540* | *0.263* | *0.260* | *0.297* |

`GOOD_POLICY` and `BAD_POLICY` are fixed scripted lever sets, not agents. They bracket the scenario
and show it is both winnable and losable.

Cost, same runs:

| Mode | Tokens | LLM calls | SQL queries |
| --- | ---: | ---: | ---: |
| `agent_raw` | 242,289 | 30 | 77 |
| `agent_datahub` | 286,810 | 29 | 76 |
| `agent_datahub_live` | 313,163 | 26 | **39** |

The best mode issued half the queries of the worst. It was not searching; it knew where to look.

## The finding

**Descriptive metadata did not measurably help. Prescriptive metadata did.**

Four paired runs of `agent_raw` vs `agent_datahub`, in chronological order:

| Run | `agent_raw` | `agent_datahub` | Gap |
| --- | ---: | ---: | ---: |
| B | 0.6356 | 0.6807 | +0.045 |
| C | 0.6152 | 0.6580 | +0.043 |
| D | 0.6733 | 0.6338 | **−0.040** |
| E | 0.6837 | 0.7362 | +0.053 |

Runs B–D carried descriptions, glossary and *table-level* lineage. The sign flipped in run D, and
run-to-run variation on identical configurations reached 0.02, so that gap was never distinguishable
from noise. The honest reading of B–D is **no measurable effect**.

Run E is the first with column-level lineage and documented response times, and it is the only one
where the ordering is clean. One run is not proof, but the mechanism is legible: see below.

### Why descriptions alone did so little

The warehouse has readable names — `income_tax_rate`, `road_maintenance_budget`, `outage_fraction`.
`agent_raw` reads them through `information_schema` and infers most of what a description would have
told it. Of 123 column descriptions in the catalog, **37 restate the column name**
(`income_tax_revenue: Income tax collected`). Against a self-documenting schema, that is not
information.

`docs/DECISIONS.md` anticipated this and specified a control catalog with opaque names
(`t_person_m`, `t_budg_m`). It is built and emitted by `uv run datahub-emit --baseline` — but the
agent modes query the real warehouse, so the handicap was never applied. **This is the single
biggest weakness in the comparison** and the first thing to fix.

### Why the assertions worked

Two things the data cannot supply at any query budget:

**1. Every lever is constant across the entire recorded history.**

```
income_tax_rate          distinct=1  min=0.04  max=0.04
road_maintenance_budget  distinct=1  min=0.0   max=0.0
... all 8 levers, all 60 months
```

There is no variation from which to learn that `income_tax_rate` moves `income_tax_revenue`. The
catalog is the only place that relationship exists — which is exactly what column-level lineage
carries, and what table-level lineage (`derived from: lever_monthly, citizen_monthly`) throws away.

**2. The fiscal half of the crisis has no visible damage signature.**

Roads announce themselves: `wear = 0.97`. A starved tax rate looks like a policy choice. Across
*every run before assertions*, in every mode, no agent ever changed `income_tax_rate` — while all of
them fixed the roads. Solvency ended between 0.042 and 0.467. With assertions it reached 0.829.

## Method

- **Identical by construction.** The three agent modes are one class instantiated three times, with
  `catalog` and `monitor` as the only differing arguments. `tests/test_agent.py` fails if system
  prompts, tool declarations or turn messages differ in anything else.
- **No mode is told the scoring function**, its components, or the threshold.
- **No city-state figure appears in any prompt.** Everything is discovered through SQL.
- **Each run starts from an empty warehouse**, so planner statistics and table sizes are identical.
- **Assertions are derived from `sim/systems.py`**, not fitted to outputs, and
  `tests/test_operational_assertions.py` re-derives both the sweep and the arithmetic. Two of our own
  errors were caught this way — see below.

### What the assertions say, and do not say

They state operating ranges, the measured impact of each lever, and how fast each system responds.
They never name a lever to pull. Example of what the agent receives:

```
road_monthly.wear = 0.969 -- above the documented maximum of 0.15
income_tax_rate = 0.04 -- below the documented range 0.1-0.14 [critical]
LOW YIELD -- measured to move the outcome by under 2% across their whole range: zoning_release
```

The "low yield" line is guidance about what *not* to do, and it matters as much as the rest: an
agent with twelve turns that spends one hunting for the optimum of a lever which cannot move the
outcome has burned a turn it cannot get back.

Because the assertions encode expert knowledge of the system, the claim this run supports is
narrower than "DataHub helps": it is **"a catalog carrying expert-authored assertions lets an agent
match expert play."** That is a real DataHub capability and a real result, but it should be read for
what it is.

## Caveats

1. **One seed, one run per mode** in the headline. The `agent_datahub_live` margin (+0.13) is well
   outside the 0.02 observed variance; the `agent_datahub` margin (+0.05) is not comfortably so.
2. **`agent_raw` is not fully blind** — see above.
3. **The `human` mode has not been played end to end.** The lever panel and scene work; the upstream
   Analytics Agent is not wired in, so there is no human baseline.
4. **The assertions were authored by us**, with access to the simulation source. In a real
   deployment a domain expert writes them from operational experience. The analogy holds; it is not
   identical.

## Bugs that changed the numbers

Recorded because each one silently corrupted results while every test passed. Full detail in
`docs/ERRORS.md`.

- **The agent could not see its own decisions.** `WarehouseWriter` batches at 5,000 rows;
  `citizen_monthly` writes ~3,235 a month and trickled through, while `ticks` (one row a month) and
  `road_monthly` never reached the threshold and stayed frozen at the last month of the crisis for
  entire runs. `max(tick)` never moved, and joins across tables were misaligned by months. Fixing it
  was worth about +0.06 to `agent_raw` alone.
- **The glossary was emitted and never delivered.** Twenty terms went into DataHub as free-floating
  entities with nothing linking them to a dataset, so the catalog block promised "business glossary
  definitions" and shipped none — through every run, invisible in every report.
- **No memory between turns.** Each turn opened on a blank conversation. The agent re-ran
  `information_schema` 29 times in one run and issued the same fatal fan-out join on four separate
  turns, each killed by the statement timeout, because nothing carried the lesson forward.
- **Timeouts were invisible.** A run that lost four queries and three minutes printed `0 errors`,
  because the error field only captured LLM failures.
- **A satisfaction trend detector that was exactly backwards.** In a collapsing city satisfaction
  *rises* — neglect drives a third of the population out and the survivors get shorter commutes —
  so the detector stayed silent on the failing city and fired on the healthy one. Caught by the
  validation before it shipped.
- **`transit_fare` labelled "low yield"** when it moves the outcome 2.8%. Also caught by validation.
  Telling an agent to ignore something that matters is the most damaging error this layer can make.

## Reproducing

```bash
uv run eval --dry-run
```

Verifies the whole harness with scripted policies, free. Then:

```bash
uv run eval --live --repeat 3
```

Roughly 2 minutes and ~300k tokens per mode-run.
