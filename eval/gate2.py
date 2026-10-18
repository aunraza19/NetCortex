"""Credentialed, bounded Gate 2 smoke runner.

This command is intentionally not part of CI. It writes only sanitized summaries and uses
existing core tables; it never migrates, deletes, or changes router configuration.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import re
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from netcortex_core import (
    IFACE_COLUMNS,
    PROBE_COLUMNS,
    SUBSCRIBER_COLUMNS,
    DetectionResult,
    MetricsWindow,
    ModuleUnavailable,
    SubscriberMetric,
    parse_series_key,
)
from netcortex_core import db as core_db
from netcortex_core.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SITE_ID = "north-tower"
SEED = 20261018
CADENCE_SECONDS = 12
CURRENT_MINUTES = 30
HISTORY_MINUTES = 60
PROBE_TARGETS = ("1.1.1.1", "dns:1.1.1.1")
PRIMARY_IFACE = "ether1"

_URI_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_TOKEN = re.compile(
    r"(?i)\b(?:sk|pk|hf|tabpfn)[_-][A-Za-z0-9_-]{8,}|"
    r"\b(?:api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*"
    r"(?:['\"]?)[^\s,;:'\"]+"
)


def fetch_window(conn: Any, site_id: str, start: datetime, end: datetime) -> MetricsWindow:
    """Fetch one site's source=sim metrics inside inclusive UTC bounds."""
    start, end = _utc(start), _utc(end)
    if start > end:
        raise ValueError("start must be at or before end")
    queries = (
        (
            "SELECT time, site_id, target, kind, rtt_ms, jitter_ms, loss_pct, source "
            "FROM probe_metrics WHERE site_id = %s AND source = 'sim' "
            "AND time >= %s AND time <= %s ORDER BY time",
            PROBE_COLUMNS,
        ),
        (
            "SELECT time, site_id, iface, rx_bps, tx_bps, util_pct, drops, errors, source "
            "FROM iface_metrics WHERE site_id = %s AND source = 'sim' "
            "AND time >= %s AND time <= %s ORDER BY time",
            IFACE_COLUMNS,
        ),
        (
            "SELECT time, site_id, ip, rx_bps, tx_bps, source FROM subscriber_metrics "
            "WHERE site_id = %s AND source = 'sim' AND time >= %s AND time <= %s ORDER BY time",
            SUBSCRIBER_COLUMNS,
        ),
    )
    frames = []
    for sql, columns in queries:
        with conn.cursor() as cursor:
            cursor.execute(sql, (site_id, start, end))
            frames.append(pd.DataFrame(cursor.fetchall(), columns=list(columns)))
    return MetricsWindow(
        as_of=end,
        probe_metrics=frames[0],
        iface_metrics=frames[1],
        subscriber_metrics=frames[2],
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Gate 2 timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _stage(name: str) -> None:
    print(f"Gate 2: {name}", flush=True)


def _row_time(value: Any) -> datetime:
    return pd.Timestamp(value).to_pydatetime()


def _seed_normal_history(conn: Any, *, site_id: str, now: datetime, seed: int) -> dict[str, int]:
    """Add missing normal samples for one bounded prior hour, without replacing Site rows."""
    from netcortex_core import IfaceMetric, ProbeMetric
    from netcortex_simgen.simulator import generate, generate_subscribers, site_from_fixture

    start = now - timedelta(minutes=HISTORY_MINUTES)
    end = now - timedelta(seconds=10)
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (site_id,))
    if core_db.fetch_site(conn, site_id) is None:
        core_db.upsert_site(conn, site_from_fixture(site_id))

    probes, interfaces, labels = generate(
        days=1,
        hours=1,
        start=start,
        seed=seed,
        site_id=site_id,
        normal_only=True,
    )
    probes = probes[(probes.time >= start) & (probes.time <= end)]
    interfaces = interfaces[(interfaces.time >= start) & (interfaces.time <= end)]
    subscribers = generate_subscribers(labels, start=start, end=now, seed=seed, site_ids=[site_id])

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT start_at, end_at FROM scenario_labels WHERE site_id = %s "
            "AND source = 'sim' AND start_at < %s "
            "AND COALESCE(end_at, 'infinity') > %s",
            (site_id, end, start),
        )
        scenario_intervals = [
            (_row_time(label_start), _row_time(label_end) if label_end else None)
            for label_start, label_end in cursor.fetchall()
        ]
        cursor.execute(
            "SELECT time, target FROM probe_metrics WHERE site_id = %s AND source = 'sim' "
            "AND time >= %s AND time <= %s",
            (site_id, start, end),
        )
        existing_probes = {(_row_time(at), str(target)) for at, target in cursor.fetchall()}
        cursor.execute(
            "SELECT time, iface FROM iface_metrics WHERE site_id = %s AND source = 'sim' "
            "AND time >= %s AND time <= %s",
            (site_id, start, end),
        )
        existing_interfaces = {(_row_time(at), str(iface)) for at, iface in cursor.fetchall()}
        cursor.execute(
            "SELECT time, ip FROM subscriber_metrics WHERE site_id = %s AND source = 'sim' "
            "AND time >= %s AND time <= %s",
            (site_id, start, end),
        )
        existing_subscribers = {(_row_time(at), str(ip)) for at, ip in cursor.fetchall()}

    def outside_scenario(value: Any) -> bool:
        at = _row_time(value)
        return not any(
            at >= left and (right is None or at < right) for left, right in scenario_intervals
        )

    new_probes = [
        ProbeMetric.model_validate(row)
        for row in probes.to_dict("records")
        if outside_scenario(row["time"])
        and (_row_time(row["time"]), str(row["target"])) not in existing_probes
    ]
    new_interfaces = [
        IfaceMetric.model_validate(row)
        for row in interfaces.to_dict("records")
        if outside_scenario(row["time"])
        and (_row_time(row["time"]), str(row["iface"])) not in existing_interfaces
    ]
    new_subscribers = [
        SubscriberMetric.model_validate(row)
        for row in subscribers.to_dict("records")
        if outside_scenario(row["time"])
        and (_row_time(row["time"]), str(row["ip"])) not in existing_subscribers
    ]
    core_db.insert_probe_metrics(conn, new_probes)
    core_db.insert_iface_metrics(conn, new_interfaces)
    core_db.insert_subscriber_metrics(conn, new_subscribers)
    return {
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "probe_rows_added": len(new_probes),
        "iface_rows_added": len(new_interfaces),
        "subscriber_rows_added": len(new_subscribers),
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "scenarios": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModuleUnavailable("Gate 2 resume state is unreadable") from exc
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or not isinstance(state.get("scenarios"), dict)
    ):
        raise ModuleUnavailable("Gate 2 resume state has an unsupported format")
    return state


def _resume_active_label(
    conn: Any, state: dict[str, Any], *, site_id: str, seed: int, now: datetime
) -> Any | None:
    """Resume only this runner's exact active SIM label confirmed by the database."""
    from netcortex_core import ScenarioLabel

    item = state["scenarios"].get(site_id)
    if not isinstance(item, dict) or item.get("seed") != seed:
        return None
    try:
        label_id = str(item["id"])
        expected_start = _utc(datetime.fromisoformat(item["start_at"]))
        expected_end = _utc(datetime.fromisoformat(item["end_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ModuleUnavailable("Gate 2 resume state entry is invalid") from exc
    now = _utc(now)
    if not expected_start <= now < expected_end:
        return None
    columns = (
        "id",
        "site_id",
        "scenario_type",
        "start_at",
        "end_at",
        "affected",
        "expected_cause",
        "expected_template",
        "expected_params",
        "seed",
        "source",
    )
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id, site_id, scenario_type, start_at, end_at, affected, expected_cause, "
            "expected_template, expected_params, seed, source FROM scenario_labels "
            "WHERE id = %s AND site_id = %s AND source = 'sim'",
            (label_id, site_id),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    data = dict(zip(columns, row, strict=True))
    if (
        str(data["id"]) != label_id
        or _utc(data["start_at"]) != expected_start
        or _utc(data["end_at"]) != expected_end
        or data["seed"] != seed
        or str(data["scenario_type"]) != "uplink_congestion"
    ):
        raise ModuleUnavailable("Gate 2 resume state does not match its stored scenario label")
    return ScenarioLabel.model_validate(data)


def _save_state(path: Path, state: dict[str, Any], label: Any) -> None:
    state.setdefault("scenarios", {})[label.site_id] = {
        "id": str(label.id),
        "site_id": label.site_id,
        "scenario_type": label.scenario_type.value,
        "start_at": label.start_at.isoformat(),
        "end_at": label.end_at.isoformat(),
        "seed": label.seed,
        "source": label.source.value,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _subset(window: MetricsWindow) -> MetricsWindow:
    probes = window.probe_metrics[window.probe_metrics.target.isin(PROBE_TARGETS)].copy()
    interfaces = window.iface_metrics[window.iface_metrics.iface.eq(PRIMARY_IFACE)].copy()
    return MetricsWindow(
        as_of=window.as_of,
        probe_metrics=probes,
        iface_metrics=interfaces,
        subscriber_metrics=window.subscriber_metrics.copy(),
    )


def _window_metrics(window: MetricsWindow) -> dict[str, Any]:
    def bounds(frame: pd.DataFrame) -> dict[str, str | None]:
        if frame.empty:
            return {"first": None, "last": None}
        times = pd.to_datetime(frame.time, utc=True)
        return {"first": times.min().isoformat(), "last": times.max().isoformat()}

    return {
        "probe": len(window.probe_metrics),
        "probe_time_range": bounds(window.probe_metrics),
        "iface": len(window.iface_metrics),
        "iface_time_range": bounds(window.iface_metrics),
        "subscriber": len(window.subscriber_metrics),
        "subscriber_time_range": bounds(window.subscriber_metrics),
    }


def _forecast_count(conn: Any, site_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM forecasts WHERE site_id = %s", (site_id,))
        row = cursor.fetchone()
    if not row:
        raise RuntimeError("forecast count query returned no row")
    return int(row[0])


def _secret_values(settings: Settings) -> list[str]:
    values = []
    for secret in (settings.database_url, settings.tabpfn_token):
        if secret is not None:
            value = secret.get_secret_value()
            if value:
                values.append(value)
    return values


def _sanitize(text: Any, secrets: list[str]) -> str:
    value = str(text)
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    value = _URI_USERINFO.sub(r"\1[REDACTED]@", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _TOKEN.sub("[REDACTED]", value)
    value = re.sub(r"[\r\n\t]+", " ", value)
    return value[:400]


def _safe_error(exc: BaseException, secrets: list[str]) -> list[str]:
    chain = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        message = _sanitize(str(current), secrets)
        chain.append(f"{type(current).__name__}: {message}" if message else type(current).__name__)
        current = current.__cause__ or current.__context__
    return chain


def _safe_frames(exc: BaseException) -> list[dict[str, Any]]:
    """Report code locations only, without source lines, locals or exception values."""
    frames = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        for frame in traceback.extract_tb(current.__traceback__):
            frames.append(
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            )
        current = current.__cause__ or current.__context__
    return frames


def _validate_result(
    result: DetectionResult,
    *,
    settings: Settings,
    as_of: datetime,
    expected_model: str,
) -> None:
    if not isinstance(result, DetectionResult):
        raise ValueError("detect did not return a core DetectionResult")
    if result.mode != settings.tabpfn_mode or result.mode not in {"cloud", "local"}:
        raise ValueError("detect did not report the configured real provider mode")
    if (
        not result.model
        or result.model != expected_model
        or result.model.startswith("fixture:")
        or "fixture" in result.model
    ):
        raise ValueError("detect reported fixture model provenance")
    if not math.isfinite(result.score):
        raise ValueError("DetectionResult score is not finite")
    origin = pd.Timestamp(as_of).floor("min")
    if not result.series:
        raise ValueError("DetectionResult contains no forecast series")
    for series in result.series:
        try:
            kind, name, metric = parse_series_key(series.series_key)
        except (ValueError, TypeError) as exc:
            raise ValueError("DetectionResult contains a noncanonical series key") from exc
        if kind not in {"probe", "iface", "subscriber"} or not name or not metric:
            raise ValueError("DetectionResult contains a noncanonical series key")
        if len(series.points) != 5:
            raise ValueError("DetectionResult forecast does not contain five horizons")
        for horizon, point in enumerate(series.points, start=1):
            at = pd.Timestamp(point.time)
            if at.tzinfo is None or at.tz_convert("UTC") != origin + pd.Timedelta(minutes=horizon):
                raise ValueError(
                    "DetectionResult forecast timestamps are not ordered +1..+5 minutes"
                )
            if not math.isfinite(point.p10 + point.p50 + point.p90):
                raise ValueError("DetectionResult forecast contains nonfinite quantiles")
            if not point.p10 <= point.p50 <= point.p90:
                raise ValueError("DetectionResult forecast quantiles are unordered")


def run_gate2(
    *,
    cases: Path,
    artifact: Path,
    out: Path,
    site_id: str = SITE_ID,
    seed: int = SEED,
    wait_seconds: int = CADENCE_SECONDS,
) -> dict[str, Any]:
    """Run one bounded real provider smoke and write a sanitized JSON/Markdown report."""
    from netcortex_detector.engine import detect
    from netcortex_detector.preparation import configure_detector, prepare_detector
    from netcortex_simgen.simulator import inject

    settings = Settings(http_timeout_s=30.0)
    secrets = _secret_values(settings)
    artifact = Path(artifact)
    cases = Path(cases)
    out = Path(out)
    state_path = artifact.parent / "state.json"
    report: dict[str, Any] = {
        "gate": "Gate 2 bounded real-provider plumbing smoke",
        "status": "failed",
        "site_id": site_id,
        "provider_mode": settings.tabpfn_mode,
        "started_at": datetime.now(UTC).isoformat(),
        "scope": {
            "site_id": site_id,
            "probe_targets": list(PROBE_TARGETS),
            "interface": PRIMARY_IFACE,
            "current_minutes": CURRENT_MINUTES,
            "history_minutes": HISTORY_MINUTES,
            "wait_seconds": wait_seconds,
            "claims": "plumbing only; no production accuracy or latency claim",
        },
        "timings_seconds": {},
    }
    stdout_capture, stderr_capture = io.StringIO(), io.StringIO()
    start_total = time.perf_counter()
    try:
        _stage("preparing context")
        state = _load_state(state_path)
        if not artifact.exists():
            t = time.perf_counter()
            prepare_detector(cases, artifact)
            report["timings_seconds"]["prepare_artifact"] = time.perf_counter() - t
        t = time.perf_counter()
        _stage("configuring real provider")
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            backend = configure_detector(artifact, settings=settings)
        report["timings_seconds"]["provider_setup"] = time.perf_counter() - t
        report["model_identity"] = _sanitize(getattr(backend, "provenance", "unknown"), secrets)
        if settings.tabpfn_mode not in {"cloud", "local"}:
            raise ModuleUnavailable("Gate 2 requires cloud or local provider mode")
        if str(getattr(backend, "provenance", "")).startswith("fixture:"):
            raise ModuleUnavailable("Gate 2 requires a real cloud or local provider")

        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            pool = core_db.get_pool(settings)
        injected_at = datetime.now(UTC)
        _stage("seeding sim history")
        with pool.connection() as conn, conn.transaction():
            label = _resume_active_label(conn, state, site_id=site_id, seed=seed, now=injected_at)
            history_anchor = label.start_at if label is not None else injected_at
            report["history_seed"] = _seed_normal_history(
                conn, site_id=site_id, now=history_anchor, seed=seed
            )
        _stage("injecting or resuming scenario")
        if label is None:
            t = time.perf_counter()
            label = inject(site_id, "uplink_congestion", 15, seed, now=injected_at)
            report["timings_seconds"]["injection"] = time.perf_counter() - t
            _save_state(state_path, state, label)
            report["injection_action"] = "created"
        else:
            report["injection_action"] = "resumed existing active label"
        report["label_id"] = str(label.id)
        report["injected_cause"] = label.expected_cause.value
        time.sleep(max(0, min(wait_seconds, 30)))
        as_of = datetime.now(UTC)
        current_start = as_of - timedelta(minutes=CURRENT_MINUTES)
        history_end = current_start - timedelta(microseconds=1)
        history_start = history_end - timedelta(minutes=HISTORY_MINUTES)
        with pool.connection() as conn:
            forecast_before = _forecast_count(conn, site_id)
            history_all = fetch_window(conn, site_id, history_start, history_end)
            current_all = fetch_window(conn, site_id, current_start, as_of)
        history, current = _subset(history_all), _subset(current_all)
        report["as_of"] = as_of.isoformat()
        report["metrics"] = {
            "history": _window_metrics(history),
            "current": _window_metrics(current),
        }
        if not history.probe_metrics.size or not history.iface_metrics.size:
            raise ModuleUnavailable(
                "bounded source=sim history lacks selected probe or interface rows"
            )
        if not current.probe_metrics.size or not current.iface_metrics.size:
            raise ModuleUnavailable(
                "bounded source=sim current window lacks selected probe or interface rows"
            )
        t = time.perf_counter()
        _stage("detecting")
        detect_error = None
        try:
            with (
                contextlib.redirect_stdout(stdout_capture),
                contextlib.redirect_stderr(stderr_capture),
            ):
                result = detect(site_id, current, history)
        except BaseException as exc:
            detect_error = exc
        report["timings_seconds"]["detect"] = time.perf_counter() - t
        with pool.connection() as conn:
            forecast_after = _forecast_count(conn, site_id)
        report["forecast_rows_before"] = forecast_before
        report["forecast_rows_after"] = forecast_after
        report["forecast_rows_changed"] = forecast_after != forecast_before
        if forecast_after != forecast_before:
            raise RuntimeError("public detect changed forecast row count")
        if detect_error is not None:
            raise detect_error
        _validate_result(
            result,
            settings=settings,
            as_of=as_of,
            expected_model=str(getattr(backend, "provenance", "")),
        )
        report["result"] = {
            "is_anomaly": result.is_anomaly,
            "score": float(result.score),
            "cause": result.cause_guess.value,
            "cause_confidence": float(result.cause_confidence),
            "cause_matches_injection": result.cause_guess == label.expected_cause,
            "model": _sanitize(result.model, secrets),
            "mode": result.mode,
            "series": [
                {
                    "series_key": series.series_key,
                    "points": len(series.points),
                    "first_time": series.points[0].time.isoformat(),
                    "last_time": series.points[-1].time.isoformat(),
                }
                for series in result.series
            ],
        }
        report["status"] = "passed"
    except BaseException as exc:
        report["error_chain"] = _safe_error(exc, secrets)
        report["error_locations"] = _safe_frames(exc)
        report["status"] = "failed"
    finally:
        report["timings_seconds"]["total"] = time.perf_counter() - start_total
        report["vendor_log_summary"] = {
            "stdout_lines_captured": len(stdout_capture.getvalue().splitlines()),
            "stderr_lines_captured": len(stderr_capture.getvalue().splitlines()),
            "contents": "captured in memory and discarded after redaction boundary",
        }
        report["finished_at"] = datetime.now(UTC).isoformat()
        _write_report(report, out, secrets)
    return report


def _write_report(report: dict[str, Any], out: Path, secrets: list[str]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    safe_report = _sanitize_tree(report, secrets)
    out.write_text(json.dumps(safe_report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result = safe_report.get("result", {})
    markdown = [
        "# Gate 2 bounded provider smoke",
        "",
        f"- Status: {safe_report['status']}",
        f"- Site: {safe_report.get('site_id', 'unknown')}",
        f"- Provider mode: {safe_report.get('provider_mode', 'unknown')}",
        f"- Model: {safe_report.get('model_identity', 'not configured')}",
        f"- As of: {safe_report.get('as_of', 'not reached')}",
        f"- Label ID: {safe_report.get('label_id', 'not created')}",
        f"- Injected cause: {safe_report.get('injected_cause', 'not created')}",
        f"- Predicted cause: {result.get('cause', 'unavailable')} "
        f"(confidence {result.get('cause_confidence', 'unavailable')})",
        f"- Cause matches injection: {result.get('cause_matches_injection', 'unavailable')}",
        f"- Anomaly: {result.get('is_anomaly', 'unavailable')}; "
        f"score: {result.get('score', 'unavailable')}",
        f"- Forecast rows before/after: {safe_report.get('forecast_rows_before', 'unknown')} / "
        f"{safe_report.get('forecast_rows_after', 'unknown')}",
        "",
        "This bounded smoke establishes plumbing only; it is not an accuracy, target recall, "
        "false-alert, or warm-latency evaluation.",
        "",
        "| Stage | Seconds |",
        "| --- | ---: |",
    ]
    for stage, seconds in safe_report.get("timings_seconds", {}).items():
        markdown.append(f"| {stage} | {seconds:.3f} |")
    markdown.extend(
        [
            "",
            "| Window | Probe rows | Interface rows | Subscriber rows |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for window, metrics in safe_report.get("metrics", {}).items():
        markdown.append(
            f"| {window} | {metrics['probe']} | {metrics['iface']} | {metrics['subscriber']} |"
        )
    markdown.extend(
        ["", "| Series | Points | First target | Last target |", "| --- | ---: | --- | --- |"]
    )
    for series in result.get("series", []):
        markdown.append(
            f"| {series['series_key']} | {series['points']} | "
            f"{series['first_time']} | {series['last_time']} |"
        )
    scope = safe_report.get("scope", {})
    if scope:
        markdown.extend(
            [
                "",
                f"Selected probes: {', '.join(scope['probe_targets'])}; "
                f"interface: {scope['interface']}.",
                "Only past source=sim observations enter detection. TRAIN supplies contexts;",
                "three normal VALIDATION references and a fixed 0.7 threshold "
                "are a limited smoke setup.",
                "The runner uses no TEST cases, performs no migration, "
                "and does not operate on home-lab.",
            ]
        )
    if safe_report.get("error_chain"):
        markdown.extend(
            [
                "",
                "Sanitized failure chain:",
                "",
                *[f"- {line}" for line in safe_report["error_chain"]],
            ]
        )
    out.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def _sanitize_tree(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_tree(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_tree(item, secrets) for item in value]
    if isinstance(value, str):
        return _sanitize(value, secrets)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded real-provider NetCortex Gate 2 smoke"
    )
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/cases")
    parser.add_argument(
        "--artifact", type=Path, default=ROOT / "data/generated/gate2/training.json"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "eval/results/gate2.json")
    parser.add_argument("--site", default=SITE_ID)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--wait-seconds", type=int, default=CADENCE_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_gate2(
            cases=args.cases,
            artifact=args.artifact,
            out=args.out,
            site_id=args.site,
            seed=args.seed,
            wait_seconds=args.wait_seconds,
        )
    except BaseException as exc:
        # Last-resort parser/path failures contain no provider or connection details.
        report = {
            "gate": "Gate 2 bounded real-provider plumbing smoke",
            "status": "failed",
            "error_chain": [f"{type(exc).__name__}: Gate 2 runner could not start"],
        }
        _write_report(report, args.out, [])
    print(f"Gate 2 {report['status']}; sanitized report saved.")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
