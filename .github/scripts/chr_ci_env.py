"""Provide a fresh, masked CHR credential to later steps in this CI job."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def write_ci_environment(path: Path) -> None:
    """Mask a job-only password, then write CHR settings to GitHub's env file."""
    password = secrets.token_urlsafe(32)
    # GitHub must learn the mask before any later step can emit this value.
    print(f"::add-mask::{password}", flush=True)
    with path.open("a", encoding="utf-8") as environment:
        environment.write("CHR_REST_URL=http://127.0.0.1:9180\n")
        environment.write("CHR_USERNAME=admin\n")
        environment.write(f"CHR_PASSWORD={password}\n")


def main() -> int:
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        print("GITHUB_ENV is required in the CHR template job", file=sys.stderr)
        return 2
    try:
        write_ci_environment(Path(env_path))
    except OSError:
        print("Could not configure the CHR job environment", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
