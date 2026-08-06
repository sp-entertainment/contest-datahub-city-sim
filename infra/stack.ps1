# Bring the whole development stack up, in order, and make it survive a Docker restart.
#
# Why this exists: DataHub's quickstart compose sets `restart: no` on all five of its
# containers, so every time the Docker engine restarts they stay down while our Postgres
# (which sets `unless-stopped`) comes back by itself. That asymmetry looked like a cascading
# failure for a while. It is not -- it is a missing restart policy, and `docker update` fixes
# it permanently for a given container.
#
# The catch: `datahub docker quickstart` RECREATES its containers and re-downloads its compose
# file, which resets the policy to `no`. So re-run this script after any quickstart.
#
#   powershell -ExecutionPolicy Bypass -File infra/stack.ps1            # bring everything up and verify
#   powershell -ExecutionPolicy Bypass -File infra/stack.ps1 -Status    # report only, change nothing

[CmdletBinding()]
param(
    [switch]$Status
)

$ErrorActionPreference = 'Stop'

# Start order matters. OpenSearch and Kafka must be healthy before GMS will come up; GMS must be
# healthy before the frontend is useful. Starting all five at once on a cold engine is what
# produced the Exited(255) mess this script exists to avoid.
$Tiers = @(
    @{ Name = 'storage and search'; Containers = @('datahub-mysql-1', 'datahub-opensearch-1', 'datahub-kafka-broker-1') },
    @{ Name = 'metadata service';   Containers = @('datahub-datahub-gms-quickstart-1') },
    @{ Name = 'frontend';           Containers = @('datahub-frontend-quickstart-1', 'datahub-datahub-actions-quickstart-1') }
)

$AllContainers = @('blindcity-postgres') + ($Tiers | ForEach-Object { $_.Containers })

function Test-Daemon {
    # $ErrorActionPreference = 'Stop' turns a native command's stderr into a terminating
    # NativeCommandError in Windows PowerShell 5.1. A dead daemon writes to stderr, so the
    # original version of this function threw in precisely the case it exists to detect --
    # the script died instead of starting Docker Desktop. Exit code, not $?, is the signal.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $null = docker info --format '{{.ServerVersion}}' 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Get-ContainerState([string]$Name) {
    $raw = docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.HostConfig.RestartPolicy.Name}}' $Name 2>$null
    if (-not $?) { return $null }
    $parts = $raw -split '\|'
    return [pscustomobject]@{
        Name    = $Name
        Status  = $parts[0]
        Health  = $parts[1]
        Restart = $parts[2]
    }
}

function Wait-Healthy([string[]]$Names, [int]$TimeoutSeconds = 300) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $pending = @()
        foreach ($n in $Names) {
            $s = Get-ContainerState $n
            if ($null -eq $s) { $pending += "$n (missing)"; continue }
            # A container with no healthcheck counts as ready once it is running.
            if ($s.Status -ne 'running') { $pending += "$n ($($s.Status))" }
            elseif ($s.Health -notin @('healthy', 'none')) { $pending += "$n ($($s.Health))" }
        }
        if ($pending.Count -eq 0) { return $true }
        Start-Sleep -Seconds 5
    }
    Write-Warning "timed out waiting for: $($pending -join ', ')"
    return $false
}

if (-not (Test-Daemon)) {
    if ($Status) { Write-Host 'docker daemon: NOT RUNNING' -ForegroundColor Red; exit 1 }

    Write-Host 'Docker daemon not responding; starting Docker Desktop...'
    Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    $deadline = (Get-Date).AddMinutes(5)
    while (-not (Test-Daemon)) {
        if ((Get-Date) -gt $deadline) { throw 'Docker daemon did not come up within 5 minutes.' }
        Start-Sleep -Seconds 5
    }
    Write-Host 'Docker daemon is up.'
}

if ($Status) {
    docker info --format 'daemon: {{.ServerVersion}}' 2>$null
    foreach ($n in $AllContainers) {
        $s = Get-ContainerState $n
        if ($null -eq $s) {
            Write-Host ('{0,-42} MISSING' -f $n) -ForegroundColor Red
            continue
        }
        $ok = $s.Status -eq 'running' -and $s.Health -in @('healthy', 'none')
        $colour = if ($ok) { 'Green' } else { 'Red' }
        $warn = if ($s.Restart -eq 'no') { '  [restart policy: no -- will not survive a Docker restart]' } else { '' }
        Write-Host ('{0,-42} {1}/{2}{3}' -f $n, $s.Status, $s.Health, $warn) -ForegroundColor $colour
    }
    exit 0
}

# The warehouse is ours and defines its own restart policy, so compose is enough.
Write-Host 'Starting warehouse Postgres...'
docker compose -f "$PSScriptRoot/postgres/docker-compose.yml" up -d | Out-Null
[void](Wait-Healthy @('blindcity-postgres') 120)

foreach ($tier in $Tiers) {
    # @(...) forces an array. Where-Object returns a bare string when exactly one item matches,
    # and passing that to a native command splats it one character at a time -- which produced
    # "No such container: d", "No such container: a", ... for the single-container GMS tier.
    $present = @($tier.Containers | Where-Object { $null -ne (Get-ContainerState $_) })
    if ($present.Count -eq 0) {
        Write-Warning "$($tier.Name): no containers found -- run 'datahub docker quickstart' first."
        continue
    }
    Write-Host "Starting $($tier.Name): $($present -join ', ')"
    docker start $present | Out-Null
    [void](Wait-Healthy $present 420)
}

# Make the whole stack survive the next engine restart. Idempotent, and the single most
# useful thing in this script.
Write-Host 'Applying restart policies...'
$existing = @($AllContainers | Where-Object { $null -ne (Get-ContainerState $_) })
docker update --restart unless-stopped $existing | Out-Null

Write-Host ''
Write-Host 'Verifying...'
$failures = 0

foreach ($n in $AllContainers) {
    $s = Get-ContainerState $n
    if ($null -eq $s -or $s.Status -ne 'running' -or $s.Health -notin @('healthy', 'none')) {
        Write-Host ('  {0,-42} NOT READY' -f $n) -ForegroundColor Red
        $failures++
    }
    else {
        Write-Host ('  {0,-42} ok' -f $n) -ForegroundColor Green
    }
}

# Container health is not the same as the service answering. Check the two endpoints the
# project actually uses.
try {
    $body = '{"query":"{ me { corpUser { username } } }"}'
    $r = Invoke-RestMethod -Uri 'http://localhost:8080/api/graphql' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 20
    if ($r.data.me.corpUser.username) {
        Write-Host ('  {0,-42} ok ({1})' -f 'GMS GraphQL :8080', $r.data.me.corpUser.username) -ForegroundColor Green
    }
    else { Write-Host ('  {0,-42} no data' -f 'GMS GraphQL :8080') -ForegroundColor Red; $failures++ }
}
catch { Write-Host ('  {0,-42} {1}' -f 'GMS GraphQL :8080', $_.Exception.Message) -ForegroundColor Red; $failures++ }

try {
    $null = docker exec blindcity-postgres psql -U blindcity -d blindcity -t -A -c 'select 1;'
    if ($?) { Write-Host ('  {0,-42} ok' -f 'warehouse SQL :5432') -ForegroundColor Green }
    else { Write-Host ('  {0,-42} query failed' -f 'warehouse SQL :5432') -ForegroundColor Red; $failures++ }
}
catch { Write-Host ('  {0,-42} {1}' -f 'warehouse SQL :5432', $_.Exception.Message) -ForegroundColor Red; $failures++ }

Write-Host ''
if ($failures -gt 0) {
    Write-Host "$failures check(s) failed. See docs/ERRORS.md." -ForegroundColor Red
    exit 1
}
Write-Host 'Stack is up and answering.' -ForegroundColor Green
exit 0
