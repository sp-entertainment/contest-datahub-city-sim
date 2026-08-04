# Slice 6 handoff — the agent arms

**Written 2026-08-03.** Read `.tasks/mvp/HANDOFF.md` first for orientation and the hard rules;
this file covers only what is specific to the agent arms and what is left to do on them.

## State: built, tested, not yet proven live

`uv run agent --arm agent_datahub|agent_raw` runs the closed loop against the live stack. 126
tests pass, ruff clean, everything pushed to `main` (`1d78683`).

What exists:

| Module | Role |
| --- | --- |
| `agent/llm.py` | Gemini over httpx, function calling, token accounting |
| `agent/tools.py` | `sql_query` (read-only) and `set_levers`. Identical for both arms |
| `agent/catalog.py` | The catalog block. **The only difference between the arms** |
| `agent/runscope.py` | Per-run view schema so SQL scoping is structural, not remembered |
| `agent/controller.py` | The loop, as a Slice 5 `Controller` |
| `agent/run.py` | Wires a run together; `ARMS` maps arm name to catalog context |

## The one thing that must not be broken

`agent_datahub` and `agent_raw` are the same object with a different `CatalogSource`. There is no
`if arm == ...` anywhere in the loop and there must never be. The moment behaviour branches on the
arm, the headline result measures the branch instead of the metadata.

Guarded by `tests/test_agent.py`: identical tool declarations, identical per-turn prompts, the
control arm's prompt containing no mention of a catalog even as a placeholder, and neither prompt
revealing the scoring function. If you change the prompt, those tests are the contract.

## What is left

1. **Finish the live smoke test.** Two turns per arm on a working model, confirming the agent
   reads the warehouse, forms a diagnosis, and sets levers. The control arm's first live run is
   what surfaced the `dict_row` bug below; it has been fixed but the fixed version has not
   completed a clean two-turn run for either arm.
2. **Record the real cost per arm** and extrapolate a 36-turn run, so H3 can be budgeted. The
   CLI already prints an extrapolation; it just needs a clean run behind it.
3. **Catalog write-back.** The fourth Slice 6 checkbox, not started. The agent should record what
   it found back into DataHub rather than working around gaps.
4. **Decide whether the MCP path matters.** See below.

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
