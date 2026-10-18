# Reset the local CHR test router (Windows PowerShell). See infra/chr/README.md.
Set-Location (Join-Path $PSScriptRoot "..\..")
uv run python infra/chr/chr.py reset
exit $LASTEXITCODE
