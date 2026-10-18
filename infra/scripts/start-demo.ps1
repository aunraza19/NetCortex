<#
Start the local NetCortex demo, each part in its own window:
Temporal (:7233), the CHR test router (REST :9180), the worker, the API and dashboard
(:8000) and the live collector (from ..\NetCortex-run). Parts already running are left
alone. Then it checks the model server and prints the dashboard URL.

    powershell -ExecutionPolicy Bypass -File infra\scripts\start-demo.ps1
#>
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CollectorRoot = Join-Path (Split-Path $Root -Parent) "NetCortex-run"

function Test-Port([int]$Port) {
    [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-Process([string]$Exe) {
    # True if a process was started from this exact executable (e.g. ...\.venv\Scripts\worker.exe).
    $pattern = [regex]::Escape($Exe)
    [bool](Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pattern })
}

function Wait-Port([int]$Port, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while (-not (Test-Port $Port)) {
        if ((Get-Date) -gt $deadline) { throw "nothing is listening on port $Port after $Seconds s" }
        Start-Sleep -Seconds 1
    }
}

function Start-Window([string]$Title, [string]$Dir, [string]$Command) {
    $script = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location '$Dir'; $Command"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $script | Out-Null
    Write-Host "started   $Title"
}

function Skip([string]$What) { Write-Host "running   $What (left as is)" }

# 1. Temporal dev server; the worker needs it before it starts.
if (Test-Port 7233) { Skip "Temporal" } else {
    New-Item -ItemType Directory -Force (Join-Path $Root "var") | Out-Null
    Start-Window "NetCortex Temporal" $Root "temporal server start-dev --db-filename var/temporal.db"
    Wait-Port 7233 60
}

# 2. CHR test router (boots in about a minute; the dry run needs it, the worker doesn't).
if (Test-Port 9180) { Skip "CHR" } else {
    Start-Window "NetCortex CHR" $Root "uv run python infra/chr/chr.py start"
}

# 3. Worker: monitors and incident workflows.
if (Test-Process (Join-Path $Root ".venv\Scripts\worker.exe")) { Skip "worker" } else {
    Start-Window "NetCortex worker" $Root "uv run worker"
}

# 4. API and dashboard.
if (Test-Port 8000) { Skip "API" } else {
    Start-Window "NetCortex API" $Root "uv run uvicorn netcortex_api.main:app --host 0.0.0.0 --port 8000"
}

# 5. Live collector, from its own checkout so it keeps running while main changes.
if (-not (Test-Path $CollectorRoot)) {
    Write-Host "skipped   collector: $CollectorRoot not found"
} elseif (Test-Process (Join-Path $CollectorRoot ".venv\Scripts\collector.exe")) { Skip "collector" } else {
    Start-Window "NetCortex collector" $CollectorRoot "uv run collector"
}

# 6. Model server, then the dashboard.
Push-Location $Root
try { uv run python infra/scripts/check_ollama.py } finally { Pop-Location }
Wait-Port 8000 90
Write-Host ""
Write-Host "Dashboard: http://localhost:8000/"
