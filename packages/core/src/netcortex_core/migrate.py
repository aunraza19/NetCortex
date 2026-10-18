"""`uv run netcortex-migrate`: apply pending SQL migrations to DATABASE_URL.

Safe to re-run: applied versions are recorded in schema_migrations and skipped, and each
migration file is itself idempotent. Never prints the database URL or its password.
"""

import argparse
import sys
from importlib.resources import files

import psycopg
from psycopg.conninfo import conninfo_to_dict

from netcortex_core.db import CONNECT_TIMEOUT_S
from netcortex_core.settings import get_settings


def migrations() -> list[tuple[str, str]]:
    """(version, sql) for every bundled migration, in order. Version = file name without .sql."""
    folder = files("netcortex_core") / "migrations"
    paths = sorted((p for p in folder.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name)
    return [(p.name.removesuffix(".sql"), p.read_text(encoding="utf-8")) for p in paths]


def apply_pending(conn: psycopg.Connection) -> list[str]:
    """Apply migrations not yet recorded; return the versions applied now."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    done = []
    for version, sql in migrations():
        if version in applied:
            continue
        with conn.transaction():
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        done.append(version)
    return done


def scrub(text: str, url: str) -> str:
    """Remove the URL and its password from an error message."""
    secrets = [url]
    try:
        password = conninfo_to_dict(url).get("password")
    except psycopg.ProgrammingError:
        password = None
    if password:
        secrets.append(str(password))
    for secret in secrets:
        text = text.replace(secret, "***")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="netcortex-migrate", description="Apply pending migrations to DATABASE_URL."
    )
    parser.add_argument(
        "--list", action="store_true", help="list bundled migrations without connecting"
    )
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(version for version, _ in migrations()))
        return 0

    settings = get_settings()
    if settings.database_url is None:
        print("DATABASE_URL is not set. Put it in .env (see .env.example).", file=sys.stderr)
        return 2
    url = settings.database_url.get_secret_value()
    try:
        with psycopg.connect(url, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True) as conn:
            done = apply_pending(conn)
    except Exception as exc:  # report any failure without leaking the URL
        print(f"Migration failed: {type(exc).__name__}: {scrub(str(exc), url)}", file=sys.stderr)
        return 1
    print(f"Applied: {', '.join(done)}" if done else "Database is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
