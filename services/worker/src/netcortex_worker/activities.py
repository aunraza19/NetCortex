"""Temporal activities: everything that touches the database, the detector or CHR.

Workflows stay deterministic; all I/O happens here. Each activity runs its blocking work in
a thread (asyncio.to_thread keeps the Sentry trace context) and writes an `events` row
whenever an incident's state changes.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import netcortex_fixes as fixes
import pandas as pd
import sentry_sdk
from netcortex_agent import facts, modules
from netcortex_agent.agent import Deps
from netcortex_core import (
    DetectionResult,
    EventKind,
    FixPlan,
    Incident,
    IncidentReport,
    IncidentStatus,
    Source,
    TemplateId,
    db,
    parse_series_key,
)
from psycopg.errors import UniqueViolation
from pydantic import BaseModel
from temporalio import activity

WINDOW = timedelta(minutes=30)
HISTORY = timedelta(hours=2)  # baseline for the detector; more is slow at 10 s resolution
STALE_AFTER = timedelta(minutes=2)
# After an incident closes, the same cause on the same site waits this long before a new one
# opens, so the tail of the same anomaly doesn't open a duplicate.
COOLDOWN = timedelta(minutes=4)  # longer than the detector's 3-minute window
VERIFY_BEFORE = timedelta(minutes=3)  # metric before the incident opened ...
VERIFY_AFTER = timedelta(minutes=2)  # ... against the last minutes of the watch period


class MonitorResult(BaseModel):
    site_id: str
    status: Literal["skipped", "normal", "already_open", "opened"]
    reason: str = ""
    incident_id: UUID | None = None
    opened_at: datetime | None = None
    prompt: str = ""
    deps: Deps | None = None


class VerifyResult(BaseModel):
    improved: bool
    detail: str


def _event(conn, kind: EventKind, incident_id: UUID, site_id: str, **payload: Any) -> None:
    db.insert_event(conn, kind, {"incident_id": str(incident_id), "site_id": site_id, **payload})


# --- Monitoring -----------------------------------------------------------------------


def _monitor(site_id: str) -> MonitorResult:
    now = datetime.now(UTC)
    with db.get_pool().connection() as conn:
        window = db.fetch_window(conn, site_id, now - WINDOW, now)
        history = db.fetch_window(conn, site_id, now - WINDOW - HISTORY, now - WINDOW)
    probes = window.probe_metrics
    if probes.empty:
        return MonitorResult(site_id=site_id, status="skipped", reason="no data")
    newest = pd.to_datetime(probes["time"], utc=True).max()
    if newest < now - STALE_AFTER:
        return MonitorResult(site_id=site_id, status="skipped", reason=f"stale since {newest}")

    with sentry_sdk.start_span(op="netcortex.detect", name=f"detect {site_id}") as span:
        try:
            detection = modules.detect(site_id, window, history)
        except Exception as exc:  # a failed detector never stops monitoring
            span.set_status("internal_error")
            return MonitorResult(
                site_id=site_id, status="skipped", reason=f"detector: {type(exc).__name__}"
            )
        span.set_data("cause_guess", detection.cause_guess.value)
        span.set_data("is_anomaly", detection.is_anomaly)

    with db.get_pool().connection() as conn:
        db.upsert_forecasts(conn, site_id, detection)
        if not detection.is_anomaly:
            return MonitorResult(site_id=site_id, status="normal")
        if db.has_open_incident(conn, site_id, detection.cause_guess.value, now - COOLDOWN):
            return MonitorResult(site_id=site_id, status="already_open")
        incident = Incident(
            site_id=site_id,
            opened_at=now,
            cause=detection.cause_guess,
            confidence=detection.cause_confidence,
            detection=detection,
            source=Source(str(probes["source"].iloc[-1])),
        )
        try:
            db.insert_incident(conn, incident)
        except UniqueViolation:
            return MonitorResult(site_id=site_id, status="already_open")
        _event(
            conn,
            EventKind.INCIDENT_OPENED,
            incident.id,
            site_id,
            status="open",
            cause=detection.cause_guess.value,
        )
        site = db.fetch_site(conn, site_id)
    return MonitorResult(
        site_id=site_id,
        status="opened",
        incident_id=incident.id,
        opened_at=now,
        prompt=facts.build_prompt(site_id, site, detection, window),
        deps=Deps.build(site_id, detection, window, site),
    )


@activity.defn
async def monitor_site(site_id: str) -> MonitorResult:
    """Load the last 30 minutes, run detect(), store forecasts, open an incident if needed."""
    return await asyncio.to_thread(_monitor, site_id)


# --- Incident steps -------------------------------------------------------------------


def _second_opinion(incident_id: UUID, site_id: str, as_of: datetime) -> DetectionResult | None:
    if not modules.tabpfn_ready():
        return None
    with db.get_pool().connection() as conn:
        window = db.fetch_window(conn, site_id, as_of - WINDOW, as_of)
        history = db.fetch_window(conn, site_id, as_of - WINDOW - HISTORY, as_of - WINDOW)
    with sentry_sdk.start_span(op="netcortex.detect", name=f"tabpfn {site_id}") as span:
        try:
            tabpfn = modules.tabpfn_detect(site_id, window, history)
        except Exception as exc:  # the incident goes on without it
            span.set_status("internal_error")
            activity.logger.warning("TabPFN second opinion failed: %s", type(exc).__name__)
            return None
    if tabpfn is None:
        return None
    with db.get_pool().connection() as conn:
        db.upsert_forecasts(conn, site_id, tabpfn)
        _event(
            conn,
            EventKind.INCIDENT_UPDATED,
            incident_id,
            site_id,
            status="open",
            note=f"TabPFN second opinion: {tabpfn.cause_guess.value}",
        )
    return tabpfn


@activity.defn
async def second_opinion(
    incident_id: UUID, site_id: str, as_of: datetime
) -> DetectionResult | None:
    """Ask the partner's TabPFN detector about a new incident; None if it isn't set up."""
    return await asyncio.to_thread(_second_opinion, incident_id, site_id, as_of)


def _save_report(incident_id: UUID, site_id: str, report: IncidentReport) -> None:
    with db.get_pool().connection() as conn:
        db.save_report(conn, incident_id, report)
        _event(
            conn,
            EventKind.INCIDENT_UPDATED,
            incident_id,
            site_id,
            status="open",
            note=f"report: {report.likely_cause.value} -> {report.template_id.value}",
        )


@activity.defn
async def save_report(incident_id: UUID, site_id: str, report: IncidentReport) -> None:
    await asyncio.to_thread(_save_report, incident_id, site_id, report)


def _check_fix(incident_id: UUID, site_id: str, template_id: TemplateId, params: dict) -> FixPlan:
    with sentry_sdk.start_span(op="netcortex.check_fix", name=f"dry run {template_id.value}"):
        plan = fixes.check_fix(incident_id, template_id, params)
    with db.get_pool().connection() as conn:
        _event(
            conn,
            EventKind.FIX_TESTED,
            incident_id,
            site_id,
            fix_plan_id=str(plan.id),
            dry_run_ok=plan.dry_run_ok,
        )
    return plan


@activity.defn
async def check_fix(
    incident_id: UUID, site_id: str, template_id: TemplateId, params: dict
) -> FixPlan:
    """Dry-run the proposed fix on CHR and store it in fix_plans."""
    return await asyncio.to_thread(_check_fix, incident_id, site_id, template_id, params)


def _set_status(incident_id: UUID, site_id: str, status: IncidentStatus, note: str) -> None:
    with db.get_pool().connection() as conn:
        db.set_incident_status(conn, incident_id, status)
        _event(
            conn, EventKind.INCIDENT_UPDATED, incident_id, site_id, status=status.value, note=note
        )


@activity.defn
async def set_status(
    incident_id: UUID, site_id: str, status: IncidentStatus, note: str = ""
) -> None:
    await asyncio.to_thread(_set_status, incident_id, site_id, status, note)


def _record_decision(fix_plan_id: UUID, decision: str, decided_by: str) -> None:
    with db.get_pool().connection() as conn:
        db.set_fix_decision(conn, fix_plan_id, decision, decided_by)


@activity.defn
async def record_decision(fix_plan_id: UUID, decision: str, decided_by: str) -> None:
    await asyncio.to_thread(_record_decision, fix_plan_id, decision, decided_by)


def _apply(plan: FixPlan, site_id: str) -> str:
    with sentry_sdk.start_span(op="netcortex.apply", name=f"apply {plan.template_id.value}"):
        output = fixes.apply(plan)
    with db.get_pool().connection() as conn:
        _event(
            conn,
            EventKind.FIX_APPLIED,
            plan.incident_id,
            site_id,
            fix_plan_id=str(plan.id),
            template_id=plan.template_id.value,
        )
    return output


@activity.defn
async def apply_fix(plan: FixPlan, site_id: str) -> str:
    """Apply an approved fix to CHR (never a real router)."""
    return await asyncio.to_thread(_apply, plan, site_id)


@activity.defn
async def rollback_fix(plan: FixPlan) -> str:
    with sentry_sdk.start_span(op="netcortex.rollback", name=f"rollback {plan.template_id.value}"):
        return await asyncio.to_thread(fixes.rollback, plan)


def _mean(window, key: str, start: datetime, end: datetime) -> float | None:
    kind, name, metric = parse_series_key(key)
    frame, column = {
        "probe": (window.probe_metrics, "target"),
        "iface": (window.iface_metrics, "iface"),
        "subscriber": (window.subscriber_metrics, "ip"),
    }[kind]
    if frame.empty:
        return None
    times = pd.to_datetime(frame["time"], utc=True)
    rows = frame[(frame[column] == name) & (times > start) & (times <= end)]
    values = pd.to_numeric(rows[metric], errors="coerce").dropna()
    return None if values.empty else float(values.mean())


def _verify(
    site_id: str, detection: DetectionResult, template_id: TemplateId, opened_at: datetime
) -> VerifyResult:
    spec = fixes.get_template(template_id).verify
    if spec is None:
        return VerifyResult(improved=True, detail="nothing to verify")
    keys = [s.series_key for s in detection.series if s.series_key.endswith(f":{spec.metric}")]
    if not keys:
        return VerifyResult(improved=False, detail=f"no {spec.metric} series in the detection")
    now = datetime.now(UTC)
    with db.get_pool().connection() as conn:
        window = db.fetch_window(conn, site_id, opened_at - VERIFY_BEFORE, now)
    details, improved = [], True
    for key in keys:
        before = _mean(window, key, opened_at - VERIFY_BEFORE, opened_at)
        after = _mean(window, key, now - VERIFY_AFTER, now)
        if before is None or after is None:
            details.append(f"{key}: not enough data")
            improved = False
            continue
        target = (
            before * (1 - spec.by_pct / 100)
            if spec.goal == "decrease"
            else before * (1 + spec.by_pct / 100)
        )
        ok = after <= target if spec.goal == "decrease" else after >= target
        improved = improved and ok
        details.append(
            f"{key}: {before:.1f} -> {after:.1f} (needed {spec.goal} by {spec.by_pct:g}%)"
        )
    return VerifyResult(improved=improved, detail="; ".join(details))


@activity.defn
async def verify_fix(
    site_id: str, detection: DetectionResult, template_id: TemplateId, opened_at: datetime
) -> VerifyResult:
    """Did the key metric improve by the template's verify rule after the fix?"""
    return await asyncio.to_thread(_verify, site_id, detection, template_id, opened_at)


ALL = [
    monitor_site,
    second_opinion,
    save_report,
    check_fix,
    set_status,
    record_decision,
    apply_fix,
    rollback_fix,
    verify_fix,
]
