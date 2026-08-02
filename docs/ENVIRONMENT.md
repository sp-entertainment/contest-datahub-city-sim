# Environment

Every command below was actually run and its result observed. Nothing here is aspirational — for
commands that have not been run yet, see the placeholders in `AGENTS.md`.

**Host of record.** Windows 11 Pro, PowerShell. 63 GB RAM, 531 GB free disk, Docker Desktop 29.2.1.
The original design machine had 8 GB and no Docker, which is why development moved.

## Verified setup

### 1. Check the machine

```powershell
$os = Get-CimInstance Win32_OperatingSystem
"RAM_GB: {0:N1}" -f ($os.TotalVisibleMemorySize/1MB)
Get-PSDrive C | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}
```

Wants 16 GB RAM and 25 GB free.

### 2. Install `uv`

```powershell
winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements --disable-interactivity
```

Installed 0.11.32. See `docs/ERRORS.md` for the PATH trap this creates in an already-open shell.

### 3. Install the DataHub CLI

```powershell
uv tool install --python 3.11 "acryl-datahub[datahub-rest]"
```

Installed `acryl-datahub` 1.6.0.17 on Python 3.11.3.

**Pin to 3.11 deliberately.** The system Python on this host is 3.14, which is ahead of what the
DataHub and Analytics Agent dependency sets expect. `--python 3.11` makes uv fetch and use its own
interpreter regardless of what is on PATH. Use the same pin for the project.

### 4. Start Docker Desktop

```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

The daemon is not up the instant the process starts. Poll rather than assume:

```powershell
for ($i=0; $i -lt 30; $i++) { docker info --format '{{.ServerVersion}}' 2>$null | Out-Null; if ($?) { "ready"; break }; Start-Sleep -Seconds 10 }
```

### 5. Bring up DataHub Core

```powershell
datahub docker quickstart
```

Resolved to quickstart plan `v1.5.0.6`. Pull plus startup took roughly four minutes on this host.

### 6. Verify DataHub

Both passed.

```powershell
Invoke-WebRequest -Uri "http://localhost:9002" -UseBasicParsing
```

Returned HTTP 200.

```powershell
Invoke-RestMethod -Uri "http://localhost:8080/api/graphql" -Method Post -ContentType "application/json" -Body '{"query":"{ me { corpUser { username } } }"}'
```

Returned `{"data":{"me":{"corpUser":{"username":"__datahub_system"}}}}` with no token supplied,
confirming writes and reads work unauthenticated.

```powershell
docker ps --format "{{.Names}}`t{{.Status}}`t{{.Ports}}"
```

## What quickstart actually brings up

Six containers, not the fourteen the original planning assumed. The current quickstart uses a
`quickstart` compose profile that is substantially leaner.

| Container | Port | Role |
| --- | --- | --- |
| `datahub-frontend-quickstart-1` | 9002 | Web UI |
| `datahub-datahub-gms-quickstart-1` | 8080 | GraphQL and REST API |
| `datahub-datahub-actions-quickstart-1` | — | Action framework |
| `datahub-mysql-1` | 3306 | DataHub's own metadata store |
| `datahub-kafka-broker-1` | 9092 | Metadata change events |
| `datahub-opensearch-1` | 9200 | Search and graph index |

**MySQL on 3306 is DataHub's internal store, not our warehouse.** Our warehouse Postgres is a
separate container and must not be confused with it. Postgres takes 5432, so there is no port
conflict — only a naming one, and it is easy to wire the Analytics Agent to the wrong one.

Compose file and config live in `C:\Users\spect\.datahub\quickstart\`. Quickstart re-downloads the
compose file on every run, so edits there do not survive unless the file is pinned — see
`docs/ERRORS.md`.

## Warehouse Postgres

Separate from DataHub's MySQL. Definition in `infra/postgres/docker-compose.yml`.

```powershell
docker compose -f infra/postgres/docker-compose.yml up -d
docker exec blindcity-postgres psql -U blindcity -d blindcity -c "select version();"
```

Verified: PostgreSQL 16.14 on 5432, container `blindcity-postgres`, healthcheck reporting healthy.
Credentials `blindcity` / `blindcity`, database `blindcity`. Data persists in the
`blindcity_blindcity_pgdata` volume; `down -v` destroys it.

This is the warehouse the simulation writes to and the agent queries. Whether the upstream Analytics
Agent issues SQL against it gets confirmed hands-on in Slice 4; the README lists PostgreSQL as a
supported source, and it does not gate the simulation either way.

## Python project

```powershell
uv sync --group dev     # creates .venv on Python 3.11, installs the project
uv run pytest -q        # 9 passing
uv run ruff check .
```

The four commands in `AGENTS.md` — `sim`, `datahub-emit`, `agent`, `eval` — all resolve, parse their
flags, and exit 1 with a pointer to the slice that implements them. That exit code is intentional: an
unimplemented command should fail, not look like a success.

## Credentials

- DataHub UI: `datahub` / `datahub`.
- GMS GraphQL at `localhost:8080/api/graphql`: unauthenticated, no token, nothing to configure.

### The one real secret: the LLM API key

Everything else here is local and unauthenticated by design. The LLM key is not.

```powershell
cp .env.example .env
# then edit .env and paste the key into GOOGLE_API_KEY
```

`.env` is gitignored; `.env.example` is committed and holds no value. Provider is Google Gemini —
`LLM_PROVIDER=google`, `GOOGLE_API_KEY=AIza...`, from https://aistudio.google.com/apikey

**Verified 2026-08-01.** The key authenticates and both `gemini-2.5-pro` and `gemini-2.5-flash` are
available on it. To re-check without exposing the value, list models with the key in a header —
never in a URL query string, where it lands in logs and history:

```powershell
Invoke-RestMethod -Uri "https://generativelanguage.googleapis.com/v1beta/models" -Headers @{ "x-goog-api-key" = $k }
```

**Model split.** Use `gemini-2.5-flash` for dry runs, smoke tests, and harness verification, and
`gemini-2.5-pro` for anything whose output is evidence — the auto-mode loop and the A/B evaluation.
Both arms of the evaluation must use the same model; that is a fairness requirement, not a
preference (`AGENTS.md`).

Rules, for humans and agents alike:

- **Never commit it.** If it lands in a commit, revoke at the provider and issue a new one —
  removing the commit is not enough, because the value was published the moment it was pushed.
- **Never paste it into a prompt, an issue, or a log.** Agents read it from the environment; no
  agent needs to see the value, and none should be asked to create one.
- Load it into the process environment from `.env` rather than passing it on the command line,
  where it lands in shell history.

## Lifecycle

```powershell
datahub docker quickstart          # start, or restart after a stop
docker ps                          # what is running
datahub docker nuke                # destroy containers and volumes, losing all catalog state
```

`datahub docker nuke` is destructive and unrecoverable. Re-ingesting the catalog after a nuke means
re-running the sim's metadata emission.
