# Errors

Log problems hit and how they were resolved, so they are not rediscovered.

## Known traps, recorded before they bite

### MCP mutation tools missing from the tool list

**Symptom.** Tools such as `add_tags` never appear, with no error.

**Cause.** Mutations are off by default and unregistered tools are silently absent.

**Fix.** Set `TOOLS_IS_MUTATION_ENABLED=true` in the MCP server configuration.

### "Generate new token" greyed out in Settings

**Symptom.** Cannot create a GMS access token from the UI.

**Cause.** Metadata Service Authentication is off by default in OSS.

**Fix.** Set `METADATA_SERVICE_AUTH_ENABLED=true` on both the `datahub-gms` and
`datahub-frontend-react` containers, then restart. Note that `datahub docker quickstart` hardcodes
`METADATA_SERVICE_AUTH_ENABLED: 'false'` for GMS and re-downloads the compose file on every run, so an
`.env` variable will not override it — the compose file must be edited and pinned.

**Applies to us?** Not currently. We run unauthenticated against `localhost:8080/api/graphql`.

### Quickstart exhausts memory

**Symptom.** Containers restart, OpenSearch or Kafka dies.

**Cause.** Quickstart needs 8 GB RAM, 2 GB swap, and 13 GB disk for its 14 containers.

**Fix.** Use a machine with 16 GB or more, since Postgres, the agent, and a browser run alongside.

**Update, 2026-08-01.** Quickstart `v1.5.0.6` brings up six containers, not fourteen — the current
`quickstart` compose profile is much leaner than this note assumed. The memory guidance still holds
as a floor. See `docs/ENVIRONMENT.md` for the observed container list.

## Problems hit

### `uv` not found immediately after `winget install`

**Symptom.** `winget install --id=astral-sh.uv` reports success, then `uv --version` in the same
shell fails with a command-not-found.

**Cause.** winget updates the machine and user PATH in the registry. An already-open shell keeps the
PATH it was started with.

**Fix.** Open a new shell, or rebuild PATH in place:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
```

Non-interactive tool sessions cannot "just open a new terminal", so the in-place rebuild is the one
that matters for agents.

### `HOME variable is not set` warnings during quickstart

**Symptom.** `datahub docker quickstart` emits repeated
`level=warning msg="The \"HOME\" variable is not set. Defaulting to a blank string."`

**Cause.** The compose file references `$HOME`, which Windows does not define — it uses `USERPROFILE`.

**Fix.** None needed. Cosmetic. All six containers came up healthy regardless. Do not chase it.

### `uv trampoline failed to canonicalize script path` for `datahub`

**Symptom.** `datahub version` fails immediately with a trampoline canonicalize error after the tool
was installed earlier.

**Cause.** The uv tool install for `acryl-datahub` was removed or its venv moved, leaving a stale
`~/.local/bin/datahub.exe` shim.

**Fix.**

```powershell
uv tool install --python 3.11 --force "acryl-datahub[datahub-rest]"
```

### Docker Desktop engine pipe vanishes mid-session

**Symptom.** `docker ps` / Postgres / DataHub all fail with
`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified` after a
successful start. Containers show `Exited (255)` after the daemon returns.

**Cause.** Docker Desktop (Windows) restarted or crashed; the named pipe goes away with the engine.
Heavy concurrent container starts right after a cold launch can also leave the engine unstable.

**Fix.** Fully quit Docker Desktop processes, relaunch `Docker Desktop.exe`, wait until
`docker info` succeeds twice ~10s apart, then `docker compose … up -d` for Postgres and
`docker start` the datahub-* containers (or `datahub docker quickstart`). Re-run `uv run sim` —
it truncates and rewrites the warehouse, so a partial run is not fatal.
