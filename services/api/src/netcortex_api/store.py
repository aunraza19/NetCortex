"""Where the API reads from: the live database, or a saved snapshot in DEMO_MODE."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from netcortex_core import (
    Event,
    FixPlan,
    Incident,
    IncidentStatus,
    db,
    parse_series_key,
)
from pydantic import BaseModel

SNAPSHOT = Path(__file__).with_name("demo") / "snapshot.json"
Health = Literal["ok", "degraded", "down", "unknown"]


class SiteHealth(BaseModel):
    id: str
    name: str
    health: Health
    worst_rtt_ms: float | None = None
    max_loss_pct: float | None = None
    uplink_util_pct: float | None = None
    open_incidents: int = 0
    updated_at: datetime | None = None
    uplinks: list[dict[str, Any]] = []


class Point(BaseModel):
    time: datetime
    value: float | None


class Band(BaseModel):
    time: datetime
    p10: float
    p50: float
    p90: float


class Series(BaseModel):
    series_key: str
    points: list[Point]
    forecast: list[Band]


class IncidentSummary(BaseModel):
    id: UUID
    site_id: str
    opened_at: datetime
    closed_at: datetime | None
    status: IncidentStatus
    cause: str
    confidence: float | None
    summary: str | None = None
    template_id: str | None = None


class IncidentDetail(BaseModel):
    incident: Incident
    fix_plan: FixPlan | None
    timeline: list[Event]


def summarize(incident: Incident) -> IncidentSummary:
    return IncidentSummary(
        **incident.model_dump(include={"id", "site_id", "opened_at", "closed_at", "status",
                                       "confidence"}),
        cause=incident.cause.value,
        summary=incident.report.summary if incident.report else None,
        template_id=incident.report.template_id.value if incident.report else None,
    )  # fmt: skip


def health_of(rows: list[tuple], open_incidents: int) -> Health:
    """rows: (target, rtt_ms, loss_pct) from the last two minutes."""
    if not rows:
        return "unknown"
    public = [r for r in rows if not r[0].startswith(("10.", "192.168.", "172.", "dns:"))]
    if public and all((r[2] or 0) >= 80 for r in public):
        return "down"
    if open_incidents or any((r[2] or 0) >= 10 for r in rows):
        return "degraded"
    return "ok"


class LiveStore:
    """Reads Tiger Cloud."""

    def sites(self) -> list[SiteHealth]:
        now = datetime.now(UTC)
        out = []
        with db.get_pool().connection() as conn:
            sites = conn.execute("SELECT id, name, uplinks FROM sites ORDER BY id").fetchall()
            for site_id, name, uplinks in sites:
                rows = conn.execute(
                    "SELECT DISTINCT ON (target) target, rtt_ms, loss_pct, time FROM probe_metrics "
                    "WHERE site_id = %s AND time > %s AND time <= %s ORDER BY target, time DESC",
                    (site_id, now - timedelta(minutes=2), now),
                ).fetchall()
                util = conn.execute(
                    "SELECT util_pct FROM iface_metrics WHERE site_id = %s AND iface = 'ether1' "
                    "AND time <= %s ORDER BY time DESC LIMIT 1",
                    (site_id, now),
                ).fetchone()
                open_count = conn.execute(
                    "SELECT count(*) FROM incidents WHERE site_id = %s AND closed_at IS NULL",
                    (site_id,),
                ).fetchone()[0]
                rtts = [r[1] for r in rows if r[1] is not None]
                out.append(SiteHealth(
                    id=site_id, name=name, health=health_of(rows, open_count),
                    worst_rtt_ms=max(rtts) if rtts else None,
                    max_loss_pct=max((r[2] for r in rows), default=None),
                    uplink_util_pct=util[0] if util else None, open_incidents=open_count,
                    updated_at=max((r[3] for r in rows), default=None), uplinks=uplinks,
                ))  # fmt: skip
        return out

    def metrics(
        self, site_id: str, start: datetime, end: datetime, keys: list[str]
    ) -> list[Series]:
        out = []
        with db.get_pool().connection() as conn:
            for key in keys:
                kind, name, metric = parse_series_key(key)
                table, column = {
                    "probe": ("probe_metrics", "target"),
                    "iface": ("iface_metrics", "iface"),
                    "subscriber": ("subscriber_metrics", "ip"),
                }[kind]
                if metric not in {"rtt_ms", "jitter_ms", "loss_pct", "util_pct", "rx_bps",
                                  "tx_bps", "drops", "errors"}:  # fmt: skip
                    raise ValueError(f"unknown metric {metric!r}")
                points = conn.execute(
                    f"SELECT time, {metric} FROM {table} WHERE site_id = %s AND {column} = %s "
                    "AND time > %s AND time <= %s ORDER BY time",
                    (site_id, name, start, min(end, datetime.now(UTC))),
                ).fetchall()
                bands = conn.execute(
                    "SELECT DISTINCT ON (time) time, p10, p50, p90 FROM forecasts "
                    "WHERE site_id = %s AND series_key = %s AND time > %s AND time <= %s "
                    "ORDER BY time",
                    (site_id, key, start, end + timedelta(minutes=5)),
                ).fetchall()
                out.append(Series(
                    series_key=key,
                    points=[Point(time=t, value=v) for t, v in points],
                    forecast=[Band(time=t, p10=a, p50=b, p90=c) for t, a, b, c in bands],
                ))  # fmt: skip
        return out

    def incidents(self, status: IncidentStatus | None) -> list[IncidentSummary]:
        columns = tuple(Incident.model_fields)
        query = f"SELECT {', '.join(columns)} FROM incidents"
        params: tuple = ()
        if status:
            query, params = query + " WHERE status = %s", (status.value,)
        with db.get_pool().connection() as conn:
            rows = conn.execute(query + " ORDER BY opened_at DESC LIMIT 200", params).fetchall()
        return [
            summarize(Incident.model_validate(dict(zip(columns, r, strict=True)))) for r in rows
        ]

    def incident(self, incident_id: UUID) -> IncidentDetail | None:
        with db.get_pool().connection() as conn:
            incident = db.fetch_incident(conn, incident_id)
            if incident is None:
                return None
            plan = db.latest_fix_plan(conn, incident_id)
            rows = conn.execute(
                "SELECT id, time, kind, payload FROM events WHERE payload->>'incident_id' = %s "
                "ORDER BY id",
                (str(incident_id),),
            ).fetchall()
        timeline = [Event(id=i, time=t, kind=k, payload=p) for i, t, k, p in rows]
        return IncidentDetail(incident=incident, fix_plan=plan, timeline=timeline)


class DemoStore:
    """Serves a snapshot of real runs (services/api/.../demo/snapshot.json). No database,
    no model, no router: approvals only move the saved incident forward in memory."""

    def __init__(self, path: Path = SNAPSHOT) -> None:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self._sites = [SiteHealth.model_validate(s) for s in data.get("sites", [])]
        self._series = {s["series_key"]: Series.model_validate(s) for s in data.get("series", [])}
        self._incidents = {
            UUID(d["incident"]["id"]): IncidentDetail.model_validate(d)
            for d in data.get("incidents", [])
        }

    def sites(self) -> list[SiteHealth]:
        return self._sites

    def metrics(
        self, site_id: str, start: datetime, end: datetime, keys: list[str]
    ) -> list[Series]:
        return [self._series[k] for k in keys if k in self._series]

    def incidents(self, status: IncidentStatus | None) -> list[IncidentSummary]:
        found = [summarize(d.incident) for d in self._incidents.values()]
        found = [i for i in found if status is None or i.status is status]
        return sorted(found, key=lambda i: i.opened_at, reverse=True)

    def incident(self, incident_id: UUID) -> IncidentDetail | None:
        return self._incidents.get(incident_id)

    def decide(self, incident_id: UUID, decision: str) -> None:
        detail = self._incidents[incident_id]
        status = IncidentStatus.RESOLVED if decision == "approved" else IncidentStatus.REJECTED
        detail.incident.status = status
        detail.incident.closed_at = datetime.now(UTC)
