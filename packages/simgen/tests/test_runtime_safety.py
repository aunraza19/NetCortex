"""Offline transaction checks for repeat runtime simulation lifecycle behavior."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from netcortex_core import Cause, TemplateId
from netcortex_fixes import validate
from netcortex_simgen import simulator


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params or ()
        self.db.statements.append((sql, self.params))

    def fetchone(self):
        if "SELECT 1 FROM scenario_labels" in self.sql:
            return (1,) if self.db.overlap else None
        if "SELECT end_at FROM scenario_labels" in self.sql:
            return (self.db.previous_end,) if self.db.previous_end else None
        return None

    def fetchall(self):
        if "SELECT time, target FROM probe_metrics" in self.sql and self.db.duplicate_probe:
            stamp, target = self.db.duplicate_probe
            start, end = self.params[1:]
            return [(stamp, target)] if start <= stamp < end else []
        return []


class FakeConnection:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def cursor(self):
        yield FakeCursor(self.db)

    @contextmanager
    def transaction(self):
        yield


class FakeDatabase:
    def __init__(self, *, overlap=False, previous_end=None, duplicate_probe=None):
        self.overlap = overlap
        self.previous_end = previous_end
        self.duplicate_probe = duplicate_probe
        self.statements = []

    @contextmanager
    def connection(self):
        yield FakeConnection(self)


def capture_inserts(monkeypatch):
    inserted = {name: [] for name in ("probe", "iface", "subscriber")}
    for name in inserted:
        monkeypatch.setattr(
            simulator.core_db,
            f"insert_{name}_metrics",
            lambda conn, rows, key=name: inserted[key].extend(rows),
        )
    return inserted


def test_runtime_overlap_rejects_before_writes(monkeypatch):
    inserted = capture_inserts(monkeypatch)
    monkeypatch.setattr(simulator.core_db, "fetch_site", lambda *_: None)
    monkeypatch.setattr(simulator.core_db, "upsert_site", lambda *_: None)
    database = FakeDatabase(overlap=True)
    with pytest.raises(ValueError, match="overlaps"):
        simulator.inject(
            "sim-tower",
            Cause.UPLINK_DOWN,
            2,
            10,
            now=datetime(2026, 10, 19, 12, tzinfo=UTC),
            database=database,
        )
    assert not any(inserted.values())
    assert not any("INSERT INTO scenario_labels" in sql for sql, _ in database.statements)


def test_runtime_backfill_skips_existing_sim_metric_key(monkeypatch):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    existing_time = now - timedelta(minutes=30)
    inserted = capture_inserts(monkeypatch)
    monkeypatch.setattr(simulator.core_db, "fetch_site", lambda *_: None)
    monkeypatch.setattr(simulator.core_db, "upsert_site", lambda *_: None)
    simulator.inject(
        "sim-tower",
        Cause.HEAVY_USER,
        2,
        11,
        now=now,
        database=FakeDatabase(duplicate_probe=(existing_time, "10.0.0.1")),
    )
    assert not any(
        row.time == existing_time and row.target == "10.0.0.1" for row in inserted["probe"]
    )
    assert any(row.target == "10.0.0.1" for row in inserted["probe"])


def test_runtime_replaces_only_bounded_sim_recovery_and_preserves_existing_site(monkeypatch):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    previous_end = now - timedelta(minutes=10)
    inserted = capture_inserts(monkeypatch)
    existing_site = simulator.site_from_fixture("sim-tower").model_copy(
        update={"name": "Operator-owned topology"}
    )
    monkeypatch.setattr(simulator.core_db, "fetch_site", lambda *_: existing_site)
    upserts = []
    monkeypatch.setattr(simulator.core_db, "upsert_site", lambda *args: upserts.append(args))
    database = FakeDatabase(previous_end=previous_end)
    simulator.inject(
        "sim-tower",
        Cause.DNS_SLOW,
        2,
        12,
        now=now,
        database=database,
    )
    deletes = [
        (sql, params)
        for sql, params in database.statements
        if sql.startswith("DELETE FROM")
    ]
    assert {sql.split()[2] for sql, _ in deletes} == {
        "probe_metrics",
        "iface_metrics",
        "subscriber_metrics",
    }
    assert all("source='sim'" in sql and "time >= %s AND time < %s" in sql for sql, _ in deletes)
    recovery_end = previous_end + timedelta(minutes=20)
    assert all(
        params == ("sim-tower", now, recovery_end) for _, params in deletes
    )
    assert not upserts
    assert inserted["probe"] and inserted["iface"] and inserted["subscriber"]


def test_original_sites_keep_their_separate_dns_lookup_target():
    for site_id in ("north-tower", "market-cafe", "east-relay"):
        keys = [target.key for target in simulator.site_from_fixture(site_id).targets]
        assert keys.count("dns:1.1.1.1") == 1


def test_supported_runtime_labels_validate_against_template_schemas():
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    supported = (
        Cause.HEAVY_USER,
        Cause.DNS_SLOW,
        Cause.UPLINK_DOWN,
        Cause.UPLINK_CONGESTION,
        Cause.UPSTREAM_DEGRADATION,
    )
    for cause in supported:
        label = simulator._runtime_label(cause, 2, 13, now)
        params = validate(label.expected_template, label.expected_params)
        if cause is Cause.DNS_SLOW:
            assert params["servers"] == ["1.1.1.1", "8.8.8.8"]
        elif label.expected_template is TemplateId.NONE:
            assert params == {}


@pytest.mark.parametrize(
    ("cause", "message"),
    [
        (Cause.GAME_ROUTE_ISSUE, "no configured game-server"),
        (Cause.WIRELESS_INTERFERENCE, "no configured wireless backhaul"),
    ],
)
def test_runtime_causes_without_matching_topology_fail_before_database_writes(
    monkeypatch, cause, message
):
    inserted = capture_inserts(monkeypatch)
    database = FakeDatabase()
    with pytest.raises(ValueError, match=message):
        simulator.inject(
            "sim-tower",
            cause,
            2,
            14,
            now=datetime(2026, 10, 19, 12, tzinfo=UTC),
            database=database,
        )
    assert not database.statements
    assert not any(inserted.values())
