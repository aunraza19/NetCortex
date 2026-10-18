# Start the local CHR test router (Windows PowerShell). See infra/chr/README.md.
Set-Location (Join-Path $PSScriptRoot "..\..")
uv run python infra/chr/chr.py start
exit $LASTEXITCODE
