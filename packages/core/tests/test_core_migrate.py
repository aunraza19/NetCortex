import re
from contextlib import nullcontext

import psycopg
import pytest
from netcortex_core import Cause, IncidentStatus, Settings, TemplateId, migrate

TABLES = [
    "sites",
    "probe_metrics",
    "iface_metrics",
    "subscriber_metrics",
    "forecasts",
    "incidents",
    "fix_plans",
    "incident_audio",
    "scenario_labels",
    "runbook_chunks",
    "events",
]
HYPERTABLES = ["probe_metrics", "iface_metrics", "subscriber_metrics", "forecasts"]


@pytest.fixture(scope="module")
def sql() -> str:
    [(version, text)] = migrate.migrations()
    assert version == "001_init"
    return text


def test_every_table_is_created(sql):
    for table in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in sql


def test_metric_tables_are_hypertables_with_site_time_indexes(sql):
    for table in HYPERTABLES:
        assert f"create_hypertable('{table}', by_range('time'), if_not_exists => TRUE)" in sql
        assert f"ON {table} (site_id, time DESC)" in sql


def test_migration_is_idempotent(sql):
    creates = re.findall(r"CREATE (?:UNIQUE )?(?:TABLE|INDEX|EXTENSION) (?!IF NOT EXISTS)", sql)
    assert creates == []
    assert "DROP TRIGGER IF EXISTS events_notify" in sql
    assert "ON CONFLICT (id) DO NOTHING" in sql  # home-lab seed


def test_check_constraints_use_the_shared_vocabulary(sql):
    for value in [*Cause, *TemplateId, *IncidentStatus]:
        assert f"'{value.value}'" in sql


def test_events_notify_the_sse_channel(sql):
    assert "pg_notify('netcortex_events'" in sql


class FakeConn:
    """Records statements and remembers which versions were applied."""

    def __init__(self):
        self.statements = []
        self.versions = set()

    def execute(self, query, params=None):
        self.statements.append(query)
        if query.startswith("INSERT INTO schema_migrations"):
            self.versions.add(params[0])
        rows = [(v,) for v in self.versions]
        return type("Cursor", (), {"fetchall": lambda self: rows})()

    def transaction(self):
        return nullcontext()


def test_apply_pending_runs_each_migration_once():
    conn = FakeConn()
    assert migrate.apply_pending(conn) == ["001_init"]
    assert migrate.apply_pending(conn) == []


def test_missing_database_url_exits_with_a_message(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(migrate, "get_settings", lambda: Settings(_env_file=None))
    assert migrate.main([]) == 2
    assert "DATABASE_URL is not set" in capsys.readouterr().err


def test_connection_errors_never_print_the_url_or_password(monkeypatch, capsys):
    password = "not-a-real-password"
    url = f"postgresql://tester:{password}@db.example.invalid:5432/tsdb"  # reserved, fake domain
    monkeypatch.setattr(migrate, "get_settings", lambda: Settings(_env_file=None, database_url=url))

    def refuse(conninfo, **kwargs):
        raise psycopg.OperationalError(f"could not connect using {conninfo} (pw {password})")

    monkeypatch.setattr(migrate.psycopg, "connect", refuse)
    assert migrate.main([]) == 1
    output = capsys.readouterr()
    assert "Migration failed: OperationalError" in output.err
    assert password not in output.err + output.out
    assert url not in output.err + output.out


def test_help_and_list_never_connect(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise AssertionError("must not connect")

    monkeypatch.setattr(migrate.psycopg, "connect", boom)
    monkeypatch.setattr(migrate, "get_settings", boom)
    with pytest.raises(SystemExit) as exit_info:
        migrate.main(["--help"])
    assert exit_info.value.code == 0
    assert migrate.main(["--list"]) == 0
    assert "001_init" in capsys.readouterr().out
