#!/usr/bin/env sh
# Stop the local CHR test router (Linux, macOS or Git Bash). See infra/chr/README.md.
cd "$(dirname "$0")/../.." && exec uv run python infra/chr/chr.py stop
