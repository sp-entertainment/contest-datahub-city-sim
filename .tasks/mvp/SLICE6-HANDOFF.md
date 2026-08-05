# Slice 6 handoff — the agent arms

**Written 2026-08-03.** Read `.tasks/mvp/HANDOFF.md` first for orientation and the hard rules;
this file covers only what is specific to the agent arms and what is left to do on them.

## BLOCKED on the API key — read this first

**2026-08-04.** Slice 6 is code-complete and cannot be validated until the key is replaced.

The key is on Google's free tier and its quota is exhausted. Current behaviour, measured:

- A single hand-made call succeeds in ~1.1s.
- Inside a run, the first call succeeds and everything after it returns **429 quota exceeded**,
  surviving five retries across ~60 seconds of waiting. That is a daily cap, not a per-minute
  burst limit — pacing does not clear it.
- Every `pro` model 429s outright. `gemini-2.5-flash` 404s with "no longer available to new
  users" while still appearing in the models listing. Only `gemini-3.6-flash`,
  `gemini-3.5-flash` and `gemini-flash-latest` respond at all.

**What is needed:** a key with billing enabled, on a paid tier. A full scored run is roughly 216
LLM calls per arm, times two arms, times however many seeds — that is not a free-tier workload.

Once the key is replaced:

1. Set `LLM_MIN_INTERVAL=0` in `.env`. The 6.5s pacing exists only for the free tier and is pure
   waiting on a paid one.
2. Re-check which models actually answer — availability has moved under this project twice.
3. `uv run agent --arm agent_raw --turns 2` then the same for `agent_datahub`.

Nothing else blocks. The stack is up, the warehouse is loaded, the tests are green.

## State: built, tested, not yet proven live

`uv run agent --arm agent_datahub|agent_raw` runs the closed loop against the live stack. 133
tests pass, ruff clean, everything pushed to `main` (`0dd11bd`).

What exists:

| Module | Role |
| --- | --- |
| `agent/llm.py` | Gemini over httpx, function calling, token accounting |
| `agent/tools.py` | `sql_query` (read-only) and `set_levers`. Identical for both arms |
| `agent/catalog.py` | The catalog block. **The only difference between the arms** |
| `agent/runscope.py` | Per-run view schema so SQL scoping is structural, not remembered |
| `agent/controller.py` | The loop, as a Slice 5 `Controller` |
| `agent/run.py` | Wires a run together; `ARMS` maps arm name to catalog context |
| `agent/writeback.py` | The agent's findings recorded back onto the datasets it queried |

## The one thing that must not be broken

`agent_datahub` and `agent_raw` are the same object with a different `CatalogSource`. There is no
`if arm == ...` anywhere in the loop and there must never be. The moment behaviour branches on the
arm, the headline result measures the branch instead of the metadata.

Guarded by `tests/test_agent.py`: identical tool declarations, identical per-turn prompts, the
control arm's prompt containing no mention of a catalog even as a placeholder, and neither prompt
revealing the scoring function. If you change the prompt, those tests are the contract.

## What is left

1. **A clean live smoke run, blocked on the key.** No run has yet completed with the agent
   actually reading data and setting levers for a stated reason. Every attempt has died on quota.
   The machinery around it is proven — the warehouse writes, the run scoping, the tool dispatch,
   the scoring, the error path — but the thing being tested has never happened.
2. **The real cost per arm.** The CLI already extrapolates; it needs one clean run behind it.
   Nothing measured so far is usable: the numbers came from runs that were mostly failed calls.
3. **Decide whether the MCP path matters.** See below.

Write-back is done (`agent/writeback.py`), but has never run against a live GMS for the same
reason — the agent has to query something before it has findings to record.

## Findings that change the plan

**The API key has no paid tier.** Verified live on 2026-08-03: every `pro` model returns 429
quota-exceeded, and `gemini-2.5-flash` now 404s with "no longer available to new users" despite
still appearing in the models listing. Working models: `gemini-3.6-flash`, `gemini-3.5-flash`,
`gemini-flash-latest`. The default is now `gemini-3.6-flash`.

This contradicts `docs/ENVIRONMENT.md`, which records both 2.5 models as available as of
2026-08-01, and it undermines the "flash for dry runs, pro for evidence" split written there.
**H3 needs a decision from the human:** enable billing to run the scored evaluation on a pro
model, or run it on flash and say so plainly in the submission. Either is defensible; running one
arm on each is not.

**Free-tier rate limits will bite a 36-turn run.** One smoke turn already hit a 429 that survived
three retries. A full run is roughly 216 LLM calls per arm. Pace the requests or expect turns to
fail — the loop treats a failed turn as a real outcome and scores the arm on the city it failed
to steer, which is correct behaviour but a poor way to lose an evaluation.

**The first live run found a bug no test caught.** The warehouse connection uses psycopg's
`dict_row` factory, so a row is a mapping; the SQL tool iterated rows directly, which yields
column *names*. Every query returned a table of its own headers. The model, seeing no data, asked
the same question six ways and burned the whole turn budget. Fixed, and guarded by
`test_sql_tool_returns_values_not_column_names`.

The test fake returned tuples while production returned dicts, so the suite was green throughout.
**A fake shaped differently from production tests nothing** — that is the same lesson as the four
saturated columns in `docs/ERRORS.md`, in a new costume.

## The MCP decision, made and open to reversal

`TASKS.md` specifies the DataHub MCP server. The catalog context is instead read from the same GMS
over GraphQL, because the MCP path needs a second process alongside a Docker stack that restarted
repeatedly on this host, and a transport failure mid-run corrupts a measurement rather than merely
inconveniencing it. The metadata is identical — the descriptions, glossary terms and lineage that
`datahub-emit` wrote.

`CatalogSource` is a Protocol precisely so an MCP-backed implementation can replace
`DataHubCatalog` without touching the controller or the parity tests. If using MCP matters for
judging, that is the seam, and it is a contained change.

The `TOOLS_IS_MUTATION_ENABLED=true` checkbox in `TASKS.md` only applies to the MCP path.

## Known limitation

A model that explicitly writes `public.road_monthly` escapes its per-run view scope and would see
pooled runs. Blocking it properly needs a dedicated read-only role. Both arms have identical
exposure so it cannot bias the comparison, and no observed query has done it — but it is real, and
worth closing before the scored run if there is time.
