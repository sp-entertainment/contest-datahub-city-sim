# Running the DataHub Analytics Agent against Blind City

`--mode agent_analytics` delegates the whole analysis to DataHub's own Analytics Agent, running as
a separate service. This directory is what it took to stand that up. Nothing here is checked out
into the repo — clone upstream, drop these three files in, and bring it up.

```bash
git clone https://github.com/datahub-project/analytics-agent.git
cd analytics-agent
cp <blindcity>/infra/analytics-agent/config.yaml .
cp <blindcity>/infra/analytics-agent/docker-compose.override.yml .
git apply <blindcity>/infra/analytics-agent/reasoning-model.patch
```

Then an `.env` alongside them:

```
DATAHUB_GMS_URL=http://host.docker.internal:8080
DATAHUB_GMS_TOKEN=unauthenticated-quickstart
BLINDCITY_URL=postgresql+psycopg2://blindcity:blindcity@host.docker.internal:5432/blindcity
LLM_PROVIDER=openai
OPENAI_API_KEY=<your key>
LLM_MODEL=gpt-5.6-luna
CHART_LLM_MODEL=gpt-5.6-luna
LLM_REASONING_EFFORT=low
```

```bash
docker compose up -d --build
uv run agent --mode agent_analytics --out results/analytics.json
```

## Why each piece is here

**`reasoning-model.patch` — the one that matters.** The Analytics Agent builds `ChatOpenAI` with
no way to set the endpoint or the reasoning budget, so it always calls `/v1/chat/completions`.
`gpt-5.6-luna` refuses function tools there unless reasoning is switched off entirely:

```
Function tools with reasoning_effort are not supported for gpt-5.6-luna in
/v1/chat/completions. To use function tools, use /v1/responses or set
reasoning_effort to 'none'.
```

Confirmed against the live API — this is a model limitation, not a key permission. The same key
succeeds on `/v1/chat/completions` at `reasoning_effort='none'`, and the refusal is a `400
invalid_request_error`, not a `401`.

That left two options. Running the advisor at `reasoning_effort='none'` would make it the only
mode with no reasoning at all while the other three run at `low` — a handicap aimed squarely at
the mode whose entire job is analysis, which would make its score meaningless. So the patch sets
`use_responses_api=True` and takes the effort from `LLM_REASONING_EFFORT`, putting every mode on
the same budget. Both are supported LangChain options; nothing is monkeypatched.

It is applied in one place, `_make_openai`, and that is sufficient: `get_llm`, `get_chart_llm`,
`get_quality_llm` and `get_delight_llm` all route through `_make_llm` to the same factory. Verified
live — the running container reports `responses_api: True, effort: low` for both the main and
chart tiers.

**Worth sending upstream.** Being unable to drive a reasoning model at all is a real limitation,
and the fix is these two options.

**`docker-compose.override.yml`** — three upstream packaging issues:

- `docker-compose.yml` sets `dockerfile: Dockerfile` but the file lives at `docker/Dockerfile`, so
  the build fails outright.
- It mounts `config.yaml` to `/app/config.yaml`, but the settings object reads
  `/root/.datahub/analytics-agent/config.yaml`. The engine list silently comes back empty and the
  agent reports it has no database.
- Its bundled Postgres publishes 5432, which our warehouse already holds. Remapped to 5433. Note
  `!override` — compose *appends* port lists from an override file rather than replacing them, so
  without it the conflict survives.

**`config.yaml`** — points the agent at DataHub for context and at our warehouse as a queryable
engine. Two details that cost time:

- The engine URL must be `postgresql+psycopg2://`. The image ships psycopg2, not psycopg v3, and a
  `+psycopg` URL fails with a missing-dependency error surfaced to the user as "the query engine is
  missing its `psycopg` dependency".
- `DATAHUB_GMS_TOKEN` must be non-empty. The DataHub context is gated on `cfg.url and cfg.token`,
  so an empty token reads as unconfigured even though our quickstart GMS ignores auth entirely. Any
  placeholder works.

## Known limitation of the current run

The agent reported *"No governed definitions or table-selection guidance were found in DataHub"*
and answered from the warehouse alone. Its DataHub context lookup is reaching GMS but not finding
our metadata, so the recorded result is closer to an *uncatalogued* analyst than a catalogued one.
Treat 0.6742 as a floor for this mode rather than a measurement of what it could do.
