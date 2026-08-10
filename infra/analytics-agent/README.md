# Running the DataHub Analytics Agent against Blind City

`--mode agent_analytics` delegates the whole analysis to DataHub's own Analytics Agent, running as
a separate service. This directory is what it took to stand that up. Nothing here is checked out
into the repo — clone upstream, drop these two files in, and bring it up.

```bash
git clone https://github.com/datahub-project/analytics-agent.git
cd analytics-agent

# One upstream change is required; see "The reasoning-model fix" below.
git remote add blindcity https://github.com/sp-entertainment/analytics-agent.git
git fetch blindcity && git checkout feat/openai-reasoning-effort

cp <blindcity>/infra/analytics-agent/config.yaml .
cp <blindcity>/infra/analytics-agent/docker-compose.override.yml .
```

Then an `.env` alongside them:

```
DATAHUB_GMS_URL=http://host.docker.internal:8080
DATAHUB_GMS_TOKEN=unauthenticated-quickstart
BLINDCITY_URL=postgresql+psycopg2://blindcity:blindcity@host.docker.internal:5432/blindcity?options=-c%20statement_timeout%3D45s
LLM_PROVIDER=openai
OPENAI_API_KEY=<your key>
LLM_MODEL=gpt-5.6-luna
CHART_LLM_MODEL=gpt-5.6-luna
QUALITY_LLM_MODEL=gpt-5.6-luna
DELIGHT_LLM_MODEL=gpt-5.6-luna
OPENAI_REASONING_EFFORT=low
```

```bash
docker compose up -d --build
uv run agent --mode agent_analytics --out results/analytics.json
```

**The `statement_timeout` in the connection URL is not optional.** Our own agent runs every query
under a 45s cap (`runscope.STATEMENT_TIMEOUT_SECONDS`); the advisor connects with its own engine,
which that cap never touched. That is unfair in this mode's favour — an unlimited query budget
against arms that have one — and it is also a hang. An advisor aggregate over `citizen_monthly`
with no `tick` filter ran for **21 minutes**, and because it outlived the run that asked for it, it
held a lock that blocked the next run's warehouse reset indefinitely. Passing the option in the URL
puts both sides on the same budget without needing an upstream change.

**All four tier models are pinned, not just `LLM_MODEL`.** The Analytics Agent runs four tiers —
main, chart, quality and delight — and only the main one is set by `LLM_MODEL`; the rest fall back
to `gpt-4o-mini`. `preflight()` checks the main model alone, because that is all the service
reports, so an unpinned tier is a model difference this benchmark's own guard cannot see. It is
also a live failure: with the tiers left at their defaults the quality tier returns
`Unsupported parameter: 'reasoning.effort' is not supported with this model`, and context-quality
assessment is silently skipped for the whole run. `OPENAI_REASONING_EFFORT` applies to every
OpenAI tier, so every tier has to be a model that accepts it.

## The reasoning-model fix

The Analytics Agent builds `ChatOpenAI` with no way to set the endpoint or the reasoning budget,
so it always calls `/v1/chat/completions` — and the whole `gpt-5.6-*` family refuses function
tools there unless reasoning is switched off entirely:

```
Function tools with reasoning_effort are not supported for gpt-5.6-luna in
/v1/chat/completions. To use function tools, use /v1/responses or set
reasoning_effort to 'none'.
```

Confirmed against the live API, twice, and it is a model limitation rather than a key permission:

- The refusal is `400 invalid_request_error` on the request shape, never `401`/`403`. When the
  project genuinely lacks a model the error is unmistakable — `gpt-4o` returned
  `403 Project ... does not have access to model` before the key was widened.
- Widening the key's permissions changed nothing. The vanilla agent was re-tested afterwards and
  returned the identical `400`.
- `gpt-5.6-terra` behaves exactly the same as `gpt-5.6-luna`. This is a property of the
  `gpt-5.6-*` family, not of one model, so switching models within it does not avoid the fix.

Two paths work: `/v1/chat/completions` with `reasoning_effort='none'`, and `/v1/responses` at any
effort. The vanilla agent can reach neither, because it never sets `reasoning_effort` at all and
cannot be told to.

That left two options. Running the advisor at `reasoning_effort='none'` would make it the only
mode with no reasoning at all while the other three run at `low` — a handicap aimed squarely at
the mode whose entire job is analysis, which would make its score meaningless. So the fix adds an
`OPENAI_REASONING_EFFORT` setting that sets `use_responses_api=True` and passes the effort
through, putting every mode on the same budget. Both are supported LangChain options; nothing is
monkeypatched.

It is applied in one place, `_make_openai`, and that is sufficient: `get_llm`, `get_chart_llm`,
`get_quality_llm` and `get_delight_llm` all route through `_make_llm` to the same factory. Verified
live — the running container reports `use_responses_api=True, effort=low` for both the main and
chart tiers.

**Sent upstream** as a draft PR rather than kept as a local patch, because being unable to drive a
reasoning model at all is a real limitation of that project and not something specific to us.
Searching all 72 commits of that repository, `reasoning_effort` and `use_responses_api` have never
appeared and no gpt-5 model is referenced anywhere in its source, README, or model picker; its
OpenAI integration traces to a single commit — the initial release — targeting `gpt-4o` and
`gpt-4o-mini`. This is untested territory rather than a regression.

## Why each other piece is here

**`docker-compose.override.yml`** — three upstream packaging issues:

- `docker-compose.yml` sets `dockerfile: Dockerfile` but the file lives at `docker/Dockerfile`, so
  the build fails outright.
- It mounts `config.yaml` to `/app/config.yaml`, but the settings object reads
  `/root/.datahub/analytics-agent/config.yaml`. The engine list silently comes back empty and the
  agent reports it has no database.
- Its bundled Postgres publishes 5432, which our warehouse already holds. Remapped to 5433. Note
  `!override` — compose *appends* port lists from an override file rather than replacing them, so
  without it the conflict survives.

These are packaging problems in the repo as shipped and are not part of the upstream PR, which is
deliberately confined to the one code change.

**`config.yaml`** — points the agent at DataHub for context and at our warehouse as a queryable
engine. Two details that cost time:

- The engine URL must be `postgresql+psycopg2://`. The image ships psycopg2, not psycopg v3, and a
  `+psycopg` URL fails with a missing-dependency error surfaced to the user as "the query engine is
  missing its `psycopg` dependency".
- `DATAHUB_GMS_TOKEN` must be non-empty. The DataHub context is gated on `cfg.url and cfg.token`,
  so an empty token reads as unconfigured even though our quickstart GMS ignores auth entirely. Any
  placeholder works.

## Known limitation

On the gpt-4o runs the agent reported *"No governed definitions or table-selection guidance were
found in DataHub"* and answered from the warehouse alone. Its DataHub context lookup reaches GMS
but does not find our metadata, which makes this mode closer to an *uncatalogued* analyst than a
catalogued one. Treat its score as a floor for the mode rather than a measurement of what it could
do with the catalog attached.
