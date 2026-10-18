<#
Stop the local NetCortex demo: worker, API, collector, CHR and Temporal.

    powershell -ExecutionPolicy Bypass -File infra\scripts\stop-demo.ps1 [-KeepCollector]

-KeepCollector leaves the live collector running, so live data keeps coming in.
#>
param([switch]$KeepCollector)
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CollectorRoot = Join-Path (Split-Path $Root -Parent) "NetCortex-run"

function Stop-Exe([string]$What, [string]$Exe) {
    # Stops every process started from this executable (uv's launcher and the Python child).
    $pattern = [regex]::Escape($Exe)
    $found = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pattern }
    $found | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host ("{0,-10} {1}" -f $What, $(if ($found) { "stopped" } else { "not running" }))
}

Stop-Exe "worker" (Join-Path $Root ".venv\Scripts\worker.exe")
Stop-Exe "API" (Join-Path $Root ".venv\Scripts\uvicorn.exe")
if (-not $KeepCollector) { Stop-Exe "collector" (Join-Path $CollectorRoot ".venv\Scripts\collector.exe") }

# CHR shuts down cleanly through its own script.
Push-Location $Root
try { uv run python infra/chr/chr.py stop } finally { Pop-Location }

$temporal = Get-Process -Name temporal -ErrorAction SilentlyContinue
$temporal | Stop-Process -Force
Write-Host ("{0,-10} {1}" -f "Temporal", $(if ($temporal) { "stopped" } else { "not running" }))
