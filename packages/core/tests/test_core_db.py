from datetime import UTC, datetime
from uuid import uuid4

import pytest
from netcortex_core import (
    Cause,
    DetectionResult,
    EventKind,
    ForecastPoint,
    Incident,
    IncidentStatus,
    ProbeMetric,
    SeriesForecast,
    Settings,
    db,
)
from psycopg.types.json import Jsonb

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def executemany(self, sql, rows):
        self.log.append((sql, list(rows)))

    def fetchone(self):
        return (42,)


class FakeConn:
    def __init__(self):
        self.log = []

    def cursor(self):
        return FakeCursor(self.log)


def test_probe_rows_are_inserted_with_enum_values_in_column_order():
    conn = FakeConn()
    row = ProbeMetric(
        time=NOW, site_id="home-lab", target="dns:1.1.1.1", kind="dns",
        rtt_ms=31.5, jitter_ms=2.0, loss_pct=0, source="live",
    )  # fmt: skip
    assert db.insert_probe_metrics(conn, [row]) == 1
    sql, rows = conn.log[0]
    assert sql.startswith("INSERT INTO probe_metrics (time, site_id, target, kind, rtt_ms,")
    assert rows == [(NOW, "home-lab", "dns:1.1.1.1", "dns", 31.5, 2.0, 0.0, "live")]


def test_no_rows_means_no_query():
    conn = FakeConn()
    assert db.insert_iface_metrics(conn, []) == 0
    assert conn.log == []


def test_forecasts_are_upserted_one_row_per_point():
    detection = DetectionResult(
        is_anomaly=False, score=0.1, cause_guess=Cause.NORMAL, cause_confidence=0.9,
        model="tabpfn-3.5", mode="local",
        series=[SeriesForecast(series_key="probe:8.8.8.8:rtt_ms", points=[
            ForecastPoint(time=NOW, p10=30, p50=35, p90=45),
            ForecastPoint(time=NOW, p10=31, p50=36, p90=47),
        ])],
    )  # fmt: skip
    conn = FakeConn()
    assert db.upsert_forecasts(conn, "north-tower", detection) == 2
    sql, rows = conn.log[0]
    assert "ON CONFLICT (site_id, series_key, model, time)" in sql
    assert rows[0] == (NOW, "north-tower", "probe:8.8.8.8:rtt_ms", 30, 35, 45, "tabpfn-3.5")


def test_incident_insert_stores_nested_models_as_json():
    incident = Incident(
        site_id="north-tower", opened_at=NOW, cause=Cause.HEAVY_USER, confidence=0.6,
        source="sim",
        detection=DetectionResult(
            is_anomaly=True, score=0.9, cause_guess=Cause.HEAVY_USER, cause_confidence=0.6,
            model="mock", mode="mock",
        ),
    )  # fmt: skip
    conn = FakeConn()
    assert db.insert_incident(conn, incident) == incident.id
    _, [values] = conn.log[0]
    assert values[4] == "open" and values[5] == "heavy_user"
    assert isinstance(values[7], Jsonb) and values[7].obj["cause_guess"] == "heavy_user"
    assert values[8] is None  # no report yet


@pytest.mark.parametrize(
    ("status", "closes"), [(IncidentStatus.VERIFYING, False), (IncidentStatus.RESOLVED, True)]
)
def test_status_change_sets_closed_at_only_for_closing_statuses(status, closes):
    conn = FakeConn()
    incident_id = uuid4()
    db.set_incident_status(conn, incident_id, status)
    assert conn.log[0][1] == (status.value, closes, incident_id)


def test_insert_event_returns_the_new_id():
    conn = FakeConn()
    assert db.insert_event(conn, EventKind.INCIDENT_OPENED, {"incident_id": "x"}) == 42
    assert conn.log[0][1][0] == "incident.opened"


def test_missing_database_url_is_a_clear_error():
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        db.database_url(Settings(_env_file=None, database_url=None))


def test_fetch_site_builds_a_site_from_the_row():
    class SiteCursor(FakeCursor):
        def fetchone(self):
            uplinks = [{"iface": "ether1", "role": "primary", "capacity_mbps": 180}]
            return ("north-tower", "North Tower", uplinks, [], 120)

    class SiteConn(FakeConn):
        def cursor(self):
            return SiteCursor(self.log)

    site = db.fetch_site(SiteConn(), "north-tower")
    assert site.uplinks[0].iface == "ether1" and site.subscribers == 120
