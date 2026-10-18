"""Database access: one psycopg 3 connection pool and small insert helpers.

Helpers take an open connection so the caller decides the transaction:

    with get_pool().connection() as conn:
        insert_probe_metrics(conn, rows)
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from netcortex_core.schemas import (
    CLOSED_STATUSES,
    IFACE_COLUMNS,
    PROBE_COLUMNS,
    SUBSCRIBER_COLUMNS,
    DetectionResult,
    EventKind,
    FixPlan,
    IfaceMetric,
    Incident,
    IncidentReport,
    IncidentStatus,
    MetricsWindow,
    ProbeMetric,
    ScenarioLabel,
    Site,
    SubscriberMetric,
)
from netcortex_core.settings import Settings, get_settings

CONNECT_TIMEOUT_S = 10

_pool: ConnectionPool | None = None


def database_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    return settings.database_url.get_secret_value()


def get_pool(settings: Settings | None = None) -> ConnectionPool:
    """The process-wide pool, created on first use."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            database_url(settings),
            min_size=1,
            max_size=5,
            timeout=CONNECT_TIMEOUT_S,
            kwargs={"connect_timeout": CONNECT_TIMEOUT_S},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _value(value: Any) -> Any:
    """Python value -> what psycopg should send. Enums go as their string value."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return Jsonb(value.model_dump(mode="json"))
    if isinstance(value, dict | list):
        return Jsonb(value)
    return value


def _insert_many(
    conn: Connection, table: str, columns: Sequence[str], rows: Iterable[BaseModel]
) -> int:
    values = [tuple(_value(getattr(row, c)) for c in columns) for row in rows]
    if not values:
        return 0
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    with conn.cursor() as cur:
        cur.executemany(sql, values)
    return len(values)


def insert_probe_metrics(conn: Connection, rows: Iterable[ProbeMetric]) -> int:
    return _insert_many(conn, "probe_metrics", PROBE_COLUMNS, rows)


def insert_iface_metrics(conn: Connection, rows: Iterable[IfaceMetric]) -> int:
    return _insert_many(conn, "iface_metrics", IFACE_COLUMNS, rows)


def insert_subscriber_metrics(conn: Connection, rows: Iterable[SubscriberMetric]) -> int:
    return _insert_many(conn, "subscriber_metrics", SUBSCRIBER_COLUMNS, rows)


def upsert_forecasts(conn: Connection, site_id: str, detection: DetectionResult) -> int:
    """Write the detector's forecast bands. Re-running a detection overwrites the same rows."""
    values = [
        (point.time, site_id, series.series_key, point.p10, point.p50, point.p90, detection.model)
        for series in detection.series
        for point in series.points
    ]
    if not values:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO forecasts (time, site_id, series_key, p10, p50, p90, model) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (site_id, series_key, model, time) "
            "DO UPDATE SET p10 = EXCLUDED.p10, p50 = EXCLUDED.p50, p90 = EXCLUDED.p90",
            values,
        )
    return len(values)


def upsert_site(conn: Connection, site: Site) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sites (id, name, uplinks, targets, subscribers) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, uplinks = EXCLUDED.uplinks, "
            "targets = EXCLUDED.targets, subscribers = EXCLUDED.subscribers",
            (
                site.id,
                site.name,
                Jsonb([u.model_dump(mode="json") for u in site.uplinks]),
                Jsonb([t.model_dump(mode="json") for t in site.targets]),
                site.subscribers,
            ),
        )


def insert_incident(conn: Connection, incident: Incident) -> UUID:
    """Insert a new incident. Fails (unique index) if one is already open for site + cause."""
    _insert_many(conn, "incidents", tuple(Incident.model_fields), [incident])
    return incident.id


def set_incident_status(conn: Connection, incident_id: UUID, status: IncidentStatus) -> None:
    """Change status; closing statuses also set closed_at."""
    closed = status in CLOSED_STATUSES
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE incidents SET status = %s, "
            "closed_at = CASE WHEN %s THEN now() ELSE closed_at END WHERE id = %s",
            (status.value, closed, incident_id),
        )


def insert_event(conn: Connection, kind: EventKind, payload: dict[str, Any]) -> int:
    """Append to `events`; the table's trigger NOTIFYs the API's SSE stream."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (kind, payload) VALUES (%s, %s) RETURNING id",
            (kind.value, Jsonb(payload)),
        )
        row = cur.fetchone()
    assert row is not None
    return row[0]


def fetch_site(conn: Connection, site_id: str) -> Site | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, uplinks, targets, subscribers FROM sites WHERE id = %s", (site_id,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    site_id, name, uplinks, targets, subscribers = row
    return Site(id=site_id, name=name, uplinks=uplinks, targets=targets, subscribers=subscribers)


def insert_fix_plan(conn: Connection, plan: FixPlan) -> UUID:
    _insert_many(conn, "fix_plans", tuple(FixPlan.model_fields), [plan])
    return plan.id


def insert_scenario_label(conn: Connection, label: ScenarioLabel) -> UUID:
    _insert_many(conn, "scenario_labels", tuple(ScenarioLabel.model_fields), [label])
    return label.id


def fetch_window(conn: Connection, site_id: str, start: datetime, as_of: datetime) -> MetricsWindow:
    """Metrics for one site with start < time <= as_of (rows dated in the future are left out)."""
    frames = {}
    for table, columns in (
        ("probe_metrics", PROBE_COLUMNS),
        ("iface_metrics", IFACE_COLUMNS),
        ("subscriber_metrics", SUBSCRIBER_COLUMNS),
    ):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(columns)} FROM {table} "
                "WHERE site_id = %s AND time > %s AND time <= %s ORDER BY time",
                (site_id, start, as_of),
            )
            frames[table] = pd.DataFrame(cur.fetchall(), columns=list(columns))
    return MetricsWindow(
        as_of=as_of,
        probe_metrics=frames["probe_metrics"],
        iface_metrics=frames["iface_metrics"],
        subscriber_metrics=frames["subscriber_metrics"],
    )


def has_open_incident(conn: Connection, site_id: str, cause: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM incidents WHERE site_id = %s AND cause = %s AND closed_at IS NULL",
            (site_id, cause),
        )
        return cur.fetchone() is not None


def fetch_incident(conn: Connection, incident_id: UUID) -> Incident | None:
    columns = tuple(Incident.model_fields)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(columns)} FROM incidents WHERE id = %s", (incident_id,))
        row = cur.fetchone()
    return None if row is None else Incident.model_validate(dict(zip(columns, row, strict=True)))


def save_report(conn: Connection, incident_id: UUID, report: IncidentReport) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE incidents SET report = %s, cause = %s, confidence = %s WHERE id = %s",
            (_value(report), report.likely_cause.value, report.confidence, incident_id),
        )


def latest_fix_plan(conn: Connection, incident_id: UUID) -> FixPlan | None:
    columns = tuple(FixPlan.model_fields)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(columns)} FROM fix_plans WHERE incident_id = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (incident_id,),
        )
        row = cur.fetchone()
    return None if row is None else FixPlan.model_validate(dict(zip(columns, row, strict=True)))


def set_fix_decision(conn: Connection, fix_plan_id: UUID, decision: str, decided_by: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE fix_plans SET decision = %s, decided_by = %s, decided_at = now() WHERE id = %s",
            (decision, decided_by, fix_plan_id),
        )
