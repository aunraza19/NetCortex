"""NetCortex API: REST for the dashboard, SSE for live updates, Temporal signals for decisions.

    uv run uvicorn netcortex_api.main:app --host 0.0.0.0 --port 8000

The dashboard itself (one HTML page, CSS and plain JS in ui/) is served at /.

With DEMO_MODE=true it serves a saved snapshot of real runs and needs no database,
Temporal, model or router.
"""

import asyncio
import json
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from netcortex_agent import modules
from netcortex_core import Cause, IncidentStatus, ScenarioLabel, db, get_settings
from netcortex_core.tracing import init_sentry
from pydantic import BaseModel, Field
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from netcortex_api.store import (
    DemoStore,
    IncidentDetail,
    IncidentSummary,
    LiveStore,
    Series,
    SiteHealth,
)

settings = get_settings()
store: LiveStore | DemoStore = DemoStore() if settings.demo_mode else LiveStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_sentry("api", settings)  # here, not at import, so tests never report to Sentry
    yield


app = FastAPI(
    lifespan=lifespan,
    title="NetCortex API",
    version="0.1.0",
    description="Sites, metrics with forecast bands, incidents, approvals and a live event stream.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_temporal: Client | None = None
HEARTBEAT_S = 15


async def temporal() -> Client:
    global _temporal
    if _temporal is None:
        try:
            _temporal = await asyncio.wait_for(
                Client.connect(settings.temporal_address, plugins=[PydanticAIPlugin()]), 10
            )
        except (TimeoutError, RuntimeError) as exc:
            raise HTTPException(503, f"Temporal unavailable: {type(exc).__name__}") from exc
    return _temporal


class Health(BaseModel):
    status: str = "ok"
    demo_mode: bool


class Decision(BaseModel):
    decided_by: str = Field(default="owner", max_length=80)


class Accepted(BaseModel):
    incident_id: UUID
    decision: str
    note: str


class ScenarioRequest(BaseModel):
    site_id: str = "sim-tower"
    scenario_type: Cause
    duration_min: int = Field(default=5, ge=1, le=60)
    seed: int | None = None


UI = Path(__file__).parent / "ui"
app.mount("/ui", StaticFiles(directory=UI), name="ui")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(UI / "index.html")


@app.get("/health")
def health() -> Health:
    return Health(demo_mode=settings.demo_mode)


@app.get("/sites")
def sites() -> list[SiteHealth]:
    return store.sites()


@app.get("/metrics")
def metrics(
    site_id: str,
    series: Annotated[list[str], Query(description="e.g. probe:8.8.8.8:rtt_ms")],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> list[Series]:
    end = to or datetime.now(UTC)
    start = from_ or end - timedelta(minutes=30)
    try:
        return store.metrics(site_id, start, end, series)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/incidents")
def incidents(status: IncidentStatus | None = None) -> list[IncidentSummary]:
    return store.incidents(status)


@app.get("/incidents/{incident_id}")
def incident(incident_id: UUID) -> IncidentDetail:
    detail = store.incident(incident_id)
    if detail is None:
        raise HTTPException(404, "unknown incident")
    return detail


async def _decide(incident_id: UUID, decision: str, body: Decision) -> Accepted:
    detail = await asyncio.to_thread(store.incident, incident_id)
    if detail is None:
        raise HTTPException(404, "unknown incident")
    if detail.incident.status is not IncidentStatus.AWAITING_APPROVAL:
        raise HTTPException(
            409, f"incident is {detail.incident.status.value}, not awaiting_approval"
        )
    if isinstance(store, DemoStore):
        store.decide(incident_id, decision)
        return Accepted(incident_id=incident_id, decision=decision, note="demo: no router touched")
    handle = (await temporal()).get_workflow_handle(f"incident-{incident_id}")
    await handle.signal("approve" if decision == "approved" else "reject", body.decided_by)
    return Accepted(incident_id=incident_id, decision=decision, note="signal sent to the workflow")


@app.post("/incidents/{incident_id}/approve", status_code=202)
async def approve(incident_id: UUID, body: Annotated[Decision | None, Body()] = None) -> Accepted:
    return await _decide(incident_id, "approved", body or Decision())


@app.post("/incidents/{incident_id}/reject", status_code=202)
async def reject(incident_id: UUID, body: Annotated[Decision | None, Body()] = None) -> Accepted:
    return await _decide(incident_id, "rejected", body or Decision())


@app.post("/demo/scenarios", status_code=201)
async def inject_scenario(request: ScenarioRequest) -> ScenarioLabel:
    if settings.demo_mode:
        raise HTTPException(409, "scenarios can't be injected in demo mode (replayed data)")
    try:
        label = await asyncio.to_thread(
            modules.inject, request.site_id, request.scenario_type, request.duration_min,
            request.seed,
        )  # fmt: skip
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Make sure the site is being watched (no-op if its monitor already runs).
    await (await temporal()).start_workflow(
        "MonitorSiteWorkflow",
        {"site_id": request.site_id, "timing": {
            "monitor_interval_s": settings.monitor_interval_s,
            "approval_timeout_s": settings.approval_timeout_s,
            "verify_wait_s": settings.verify_wait_s,
        }},
        id=f"monitor-{request.site_id}",
        task_queue=settings.temporal_task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )  # fmt: skip
    return label


def _sse(event_id: int, kind: str, payload: dict) -> str:
    return f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"


def _event_stream(last_event_id: int | None) -> Iterator[str]:
    """Blocking generator (runs in a thread): replays missed events, then follows NOTIFY."""
    url = db.database_url(settings)
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
        conn.execute("LISTEN netcortex_events")
        if last_event_id is None:
            last_event_id = conn.execute("SELECT coalesce(max(id), 0) FROM events").fetchone()[0]
        yield ": connected\n\n"
        while True:
            rows = conn.execute(
                "SELECT id, kind, payload FROM events WHERE id > %s ORDER BY id LIMIT 200",
                (last_event_id,),
            ).fetchall()
            for event_id, kind, payload in rows:
                last_event_id = event_id
                yield _sse(event_id, kind, payload)
            started = time.monotonic()
            got = list(conn.notifies(timeout=HEARTBEAT_S, stop_after=1))
            if not got and time.monotonic() - started >= HEARTBEAT_S - 1:
                yield ": ping\n\n"


def _demo_stream() -> Iterator[str]:
    yield ": demo mode, replayed data\n\n"
    while True:
        time.sleep(HEARTBEAT_S)
        yield ": ping\n\n"


@app.get("/stream")
def stream(last_event_id: Annotated[int | None, Header()] = None) -> StreamingResponse:
    """Server-sent events: incident.opened, incident.updated, fix.tested, fix.applied.
    Reconnect with Last-Event-ID to replay what was missed."""
    body = _demo_stream() if settings.demo_mode else _event_stream(last_event_id)
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def serve() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
