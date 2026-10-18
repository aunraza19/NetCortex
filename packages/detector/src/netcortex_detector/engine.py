from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import numpy as np
import pandas as pd
from netcortex_core import (
    Cause,
    DetectionResult,
    ForecastPoint,
    MetricsWindow,
    ModuleUnavailable,
    SeriesForecast,
    Settings,
    series_key,
)

CAUSES = (
    "uplink_congestion",
    "heavy_user",
    "upstream_degradation",
    "game_route_issue",
    "wireless_interference",
    "uplink_down",
    "dns_slow",
    "normal",
)
PROBE_COLUMNS = {"time", "site_id", "target", "rtt_ms", "jitter_ms", "loss_pct"}
IFACE_COLUMNS = {"time", "site_id", "iface", "util_pct", "drops", "errors"}


class DetectorUnavailable(ModuleUnavailable):
    """The requested core or model integration is absent or failed."""


@dataclass(frozen=True)
class DetectorConfig:
    mode: str = "cloud"
    context_rows: int = 2048
    threshold: float = 0.7
    min_history_minutes: int = 5
    source_roles: dict[str, str] | None = None
    target_roles: dict[str, str] | None = None


class Backend(Protocol):
    provenance: str

    def forecasts(self, history: pd.DataFrame, horizon: int) -> list[dict[str, Any]]: ...
    def cause(self, vector: pd.Series) -> tuple[str, float]: ...
    def anomaly(self, vector: pd.Series) -> float: ...


def _utc_series(values: pd.Series, name: str) -> pd.Series:
    if any(pd.Timestamp(value).tzinfo is None for value in values if pd.notna(value)):
        raise ValueError(f"{name}.time must contain timezone-aware UTC timestamps")
    parsed = pd.to_datetime(values, utc=True, errors="coerce")
    if parsed.isna().any():
        raise ValueError(f"{name}.time contains invalid timestamps")
    return parsed


def _validate_frame(
    frame: pd.DataFrame, required: set[str], name: str, site_id: str
) -> pd.DataFrame:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(sorted(missing))}")
    result = frame.copy()
    if result.empty:
        return result
    result["time"] = _utc_series(result["time"], name)
    if not result["site_id"].eq(site_id).all():
        raise ValueError(f"{name} contains rows for a different site")
    if "source" in result and result["source"].astype(str).str.startswith("sim_supplemental").any():
        raise ValueError(f"{name} contains experimental supplemental rows")
    return result.sort_values("time", kind="stable")


def build_features(
    probes: pd.DataFrame,
    interfaces: pd.DataFrame,
    *,
    site_id: str,
    as_of: datetime | pd.Timestamp | str,
    target_roles: dict[str, str] | None = None,
    source_roles: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Build UTC minute snapshots from observations at or before as_of only."""
    p = _validate_frame(probes, PROBE_COLUMNS, "probe", site_id)
    i = _validate_frame(interfaces, IFACE_COLUMNS, "interface", site_id)
    _validate_source_consistency(p, i)
    _validate_bounds(
        p, {"rtt_ms": (0, None), "jitter_ms": (0, None), "loss_pct": (0, 100)}, "probe"
    )
    _validate_bounds(
        i, {"util_pct": (0, 100), "drops": (0, None), "errors": (0, None)}, "interface"
    )
    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = cutoff.tz_convert("UTC")
    p = p[p.time <= cutoff]
    i = i[i.time <= cutoff]
    role_map = target_roles or {}
    if not p.empty:
        p = p.copy()
        p["target_role"] = p.target.map(role_map).fillna("target:" + p.target.astype(str))
        p["minute"] = p.time.dt.floor("min")
        pg = (
            p.groupby(["minute", "target_role"], observed=True)
            .agg(
                rtt_ms=("rtt_ms", "median"),
                jitter_ms=("jitter_ms", "median"),
                loss_pct=("loss_pct", "mean"),
                samples=("time", "size"),
            )
            .reset_index()
        )
        wide = pg.pivot(
            index="minute", columns="target_role", values=["rtt_ms", "jitter_ms", "loss_pct"]
        )
        wide.columns = [f"{metric}_{role}" for metric, role in wide.columns]
        probe_features = wide
    else:
        probe_features = pd.DataFrame()
    if not i.empty:
        i = i.copy()
        i["iface_role"] = i.iface.map(source_roles or {}).fillna("interface:" + i.iface.astype(str))
        i["minute"] = i.time.dt.floor("min")
        ig = i.groupby(["minute", "iface_role"], observed=True).agg(
            util_pct=("util_pct", "mean"),
            drops=("drops", "sum"),
            errors=("errors", "sum"),
        )
        iface_features = ig.unstack("iface_role")
        iface_features.columns = [
            f"iface_{metric}_{role}" for metric, role in iface_features.columns
        ]
    else:
        iface_features = pd.DataFrame()
    combined = probe_features.join(iface_features, how="outer").sort_index()
    if combined.empty:
        return combined
    combined = combined.loc[combined.index <= cutoff.floor("min")].copy()
    # No backfill: missing measurements stay missing and cannot import future values.
    combined = combined.ffill(limit=2)
    for col in list(combined.columns):
        combined[f"{col}_lag1"] = combined[col].shift(1)
        combined[f"{col}_mean5"] = combined[col].rolling(5, min_periods=3).mean().shift(1)
        combined[f"{col}_std5"] = combined[col].rolling(5, min_periods=3).std().shift(1)
    minutes = combined.index
    combined["minute_of_day"] = minutes.hour * 60 + minutes.minute
    combined["day_of_week"] = minutes.dayofweek
    combined.index.name = "time"
    return combined.replace([np.inf, -np.inf], np.nan)


def _validate_bounds(
    frame: pd.DataFrame, limits: dict[str, tuple[float, float | None]], name: str
) -> None:
    for column, (lower, upper) in limits.items():
        values = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].notna().ne(values.notna()).any():
            raise ValueError(f"{name}.{column} contains nonnumeric observations")
        if (values.dropna() < lower).any() or (
            upper is not None and (values.dropna() > upper).any()
        ):
            raise ValueError(f"{name}.{column} is outside its valid range")


def _vector(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    prior = frame.loc[frame.index <= as_of.floor("min")]
    if prior.empty:
        return pd.Series(dtype=float)
    row = prior.iloc[-1]
    return pd.to_numeric(row, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)


def consecutive_forecast_exceedances(
    observed: pd.Series, forecasts: pd.DataFrame, *, p: str = "p90", required: int = 3
) -> int:
    """Count the trailing consecutive actuals above forecasts made before each actual."""
    required_columns = {"made_at", "target_time", p}
    if required_columns - set(forecasts.columns):
        missing = ", ".join(sorted(required_columns - set(forecasts.columns)))
        raise ValueError(f"forecasts missing columns: {missing}")
    made = pd.to_datetime(forecasts["made_at"], utc=True, errors="coerce")
    target = pd.to_datetime(forecasts["target_time"], utc=True, errors="coerce")
    rows = forecasts.copy()
    rows["made_at"], rows["target_time"] = made, target
    rows = rows[rows["made_at"] < rows["target_time"]]
    actual = observed.copy()
    actual.index = pd.to_datetime(actual.index, utc=True, errors="coerce")
    if actual.index.isna().any() or rows[["made_at", "target_time"]].isna().any().any():
        raise ValueError("observed and forecast timestamps must be valid")
    by_target = (
        rows.sort_values("made_at")
        .drop_duplicates("target_time", keep="last")
        .set_index("target_time")
    )
    hits = []
    for at, value in actual.sort_index().items():
        forecast = by_target.loc[at] if at in by_target.index else None
        hits.append(bool(forecast is not None and forecast["made_at"] < at and value > forecast[p]))
    count = 0
    for hit in reversed(hits):
        if not hit:
            break
        count += 1
    return count if count >= required else 0


def run_engine(
    probes: pd.DataFrame,
    interfaces: pd.DataFrame,
    *,
    site_id: str,
    as_of: datetime | pd.Timestamp | str,
    history_start: datetime | pd.Timestamp | str | None = None,
    backend: Backend,
    config: DetectorConfig | None = None,
    training_features: pd.DataFrame | None = None,
    training_labels: list[str] | None = None,
    anomaly_threshold: float | None = None,
) -> dict[str, Any]:
    """Independent engine entry point for an injected real provider or explicit fixture backend."""
    cfg = config or DetectorConfig()
    end = pd.Timestamp(as_of)
    if end.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    end = end.tz_convert("UTC")
    features = build_features(
        probes,
        interfaces,
        site_id=site_id,
        as_of=end,
        target_roles=cfg.target_roles,
        source_roles=cfg.source_roles,
    )
    if probes.empty:
        return _empty_result(site_id, end, backend.provenance, "missing_probe_data")
    if interfaces.empty:
        return _empty_result(site_id, end, backend.provenance, "missing_interface_data")
    for frame, kind in ((probes, "probe"), (interfaces, "interface")):
        past = frame.loc[pd.to_datetime(frame["time"], utc=True) <= end]
        if past.empty:
            return _empty_result(site_id, end, backend.provenance, f"missing_{kind}_data")
        latest = pd.to_datetime(past["time"], utc=True).max()
        if end - latest > pd.Timedelta(minutes=2):
            return _empty_result(site_id, end, backend.provenance, "stale_data")
    if history_start is not None:
        start = pd.Timestamp(history_start)
        if start.tzinfo is None:
            raise ValueError("history_start must be timezone-aware")
        features = features.loc[features.index >= start.tz_convert("UTC")]
    if len(features.dropna(how="all")) < cfg.min_history_minutes:
        return _empty_result(site_id, end, backend.provenance, "insufficient_history")
    if end.floor("min") - features.index.max() > pd.Timedelta(minutes=2):
        return _empty_result(site_id, end, backend.provenance, "stale_data")
    if not _has_finite_evidence(features):
        return _empty_result(site_id, end, backend.provenance, "invalid_measurements")
    vector = _vector(features, end)
    try:
        inference_features = features.tail(cfg.context_rows)
        if getattr(backend, "supports_parallel_inference", False):
            forecasts, sustained, cause, confidence, raw_anomaly = _parallel_inference(
                backend,
                inference_features,
                vector,
                cfg,
                training_features,
                training_labels,
            )
        else:
            forecasts = backend.forecasts(inference_features, 5)
            sustained = _walk_forward_exceedances(inference_features, backend, cfg)
            cause, confidence = _infer_cause(
                backend, vector, training_features, training_labels
            )
            raw_anomaly = float(backend.anomaly(vector))
        _validate_forecast_rows(forecasts)
        if not np.isfinite(confidence) or not np.isfinite(raw_anomaly):
            raise DetectorUnavailable("backend returned a nonfinite score or confidence")
        anomaly = float(np.clip(raw_anomaly, 0.0, 1.0))
    except Exception as exc:
        raise DetectorUnavailable(
            f"{backend.provenance} inference failed ({type(exc).__name__})"
        ) from exc
    if cause not in CAUSES:
        raise DetectorUnavailable(f"backend returned unsupported cause {cause!r}")
    threshold = float(
        np.clip(anomaly_threshold if anomaly_threshold is not None else cfg.threshold, 0.0, 1.0)
    )
    anomalous = bool(sustained or anomaly >= threshold)
    evidence = [
        f"{key} observed {value:.2f} at {end.isoformat()}"
        for key, value in vector.items()
        if key.startswith(("iface_util_pct", "loss_pct", "rtt_ms"))
        and np.isfinite(value)
        and abs(float(value)) > 0
    ][:8]
    return {
        "site_id": site_id,
        "as_of": end.isoformat(),
        "is_anomaly": anomalous,
        "anomaly_score": anomaly,
        "threshold": threshold,
        "cause": cause,
        "cause_confidence": float(np.clip(confidence, 0.0, 1.0)),
        "forecasts": forecasts,
        "evidence": evidence,
        "status": "ok",
        "availability": "available",
        "provenance": backend.provenance,
        "supplemental_used": False,
        "sustained_forecast_exceedance": sustained,
    }


def _infer_cause(
    backend: Backend,
    vector: pd.Series,
    training_features: pd.DataFrame | None,
    training_labels: list[str] | None,
) -> tuple[str, float]:
    if (
        training_features is not None
        and training_labels is not None
        and hasattr(backend, "predict_cause")
    ):
        cause, confidence = backend.predict_cause(vector, training_features, training_labels)
    else:
        cause, confidence = backend.cause(vector)
    return cause, float(confidence)


def _parallel_inference(
    backend: Backend,
    features: pd.DataFrame,
    vector: pd.Series,
    config: DetectorConfig,
    training_features: pd.DataFrame | None,
    training_labels: list[str] | None,
) -> tuple[list[dict[str, Any]], bool, str, float, float]:
    """Overlap independent provider paths only for backends opting in explicitly."""
    prepare = getattr(backend, "prepare_parallel_inference", None)
    if prepare is not None:
        prepare()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            "forecasts": executor.submit(backend.forecasts, features, 5),
            "sustained": executor.submit(
                _walk_forward_exceedances, features, backend, config
            ),
            "cause": executor.submit(
                _infer_cause, backend, vector, training_features, training_labels
            ),
            "anomaly": executor.submit(backend.anomaly, vector),
        }
        try:
            forecasts = futures["forecasts"].result()
            sustained = futures["sustained"].result()
            cause, confidence = futures["cause"].result()
            raw_anomaly = float(futures["anomaly"].result())
        except Exception:
            for future in futures.values():
                future.cancel()
            raise
    return forecasts, sustained, cause, confidence, raw_anomaly


def _walk_forward_exceedances(
    features: pd.DataFrame, backend: Backend, config: DetectorConfig
) -> bool:
    """Forecast the final three actual points from strictly earlier observations."""
    targets = [
        column
        for column in features.columns
        if column.startswith(("rtt_ms_", "loss_pct_", "iface_util_pct_"))
        and not column.endswith(("_lag1", "_mean5", "_std5"))
    ]
    times = features.index[-3:]
    if len(times) != 3:
        return False
    if any(
        (times[position] - times[position - 1]) != pd.Timedelta(minutes=1) for position in (1, 2)
    ):
        return False
    contexts: list[tuple[pd.DataFrame, pd.Timestamp]] = []
    for target_time in times:
        prior = features.loc[features.index < target_time].tail(config.context_rows)
        if len(prior) < config.min_history_minutes:
            return False
        contexts.append((prior, target_time))
    batch_method = getattr(backend, "walk_forward_forecasts", None)
    if batch_method is not None:
        results = batch_method(contexts)
    else:
        results = [backend.forecasts(prior, 1) for prior, _ in contexts]
    hits: dict[str, list[bool]] = {metric: [] for metric in targets}
    for (_, target_time), made in zip(contexts, results, strict=True):
        by_metric = {str(row["metric"]): row for row in made}
        for metric in targets:
            forecast = by_metric.get(metric)
            actual = features.loc[target_time, metric]
            admissible = (
                forecast is not None
                and pd.Timestamp(forecast["made_at"]) < target_time
                and pd.Timestamp(forecast["target_time"]) == target_time
                and int(forecast.get("horizon_minutes", -1)) == 1
            )
            hits[metric].append(
                bool(admissible and np.isfinite(actual) and float(actual) > float(forecast["p90"]))
            )
    return any(len(values) == 3 and all(values) for values in hits.values())


def _validate_source_consistency(probes: pd.DataFrame, interfaces: pd.DataFrame) -> None:
    sources = []
    source_metadata_present = []
    for name, frame in (("probe", probes), ("interface", interfaces)):
        source_metadata_present.append("source" in frame and not frame.empty)
        if "source" not in frame or frame.empty:
            continue
        values = set(frame["source"].dropna().astype(str).unique())
        if len(values) > 1:
            raise ValueError(f"{name} frame mixes measurement sources")
        if values:
            sources.append(values.pop())
    if (
        all(not frame.empty for frame in (probes, interfaces))
        and any(source_metadata_present)
        and not all(source_metadata_present)
    ):
        raise ValueError("probe and interface frames must both identify their measurement source")
    if len(set(sources)) > 1:
        raise ValueError("probe and interface frames use different measurement sources")


def _has_finite_evidence(features: pd.DataFrame) -> bool:
    if features.empty:
        return False
    row = features.iloc[-1]
    probe_valid = False
    loss_columns = [
        c
        for c in row.index
        if c.startswith("loss_pct_") and not c.endswith(("_lag1", "_mean5", "_std5"))
    ]
    for name in row.index:
        value = row[name]
        if not np.isfinite(value):
            continue
        if name.startswith("rtt_ms_") and not name.endswith(("_lag1", "_mean5", "_std5")):
            probe_valid = True
    if not probe_valid:
        probe_valid = any(
            np.isfinite(row[name]) and float(row[name]) == 100.0 for name in loss_columns
        )
    interface_valid = any(
        name.startswith(("iface_util_pct_", "iface_drops_", "iface_errors_"))
        and not name.endswith(("_lag1", "_mean5", "_std5"))
        and np.isfinite(value)
        for name, value in row.items()
    )
    return probe_valid and interface_valid


def _validate_forecast_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        try:
            metric = str(row["metric"])
            horizon = int(row["horizon_minutes"])
            low, median, high = (float(row[key]) for key in ("p10", "p50", "p90"))
            made_at = pd.Timestamp(row["made_at"])
            target_time = pd.Timestamp(row["target_time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DetectorUnavailable("backend returned malformed forecasts") from exc
        if not metric.startswith(("rtt_ms_", "loss_pct_", "iface_util_pct_")):
            raise DetectorUnavailable("backend returned an unsupported forecast metric")
        if horizon < 1 or horizon > 5:
            raise DetectorUnavailable("backend returned an unsupported forecast horizon")
        if (
            made_at.tzinfo is None
            or target_time.tzinfo is None
            or target_time.tz_convert("UTC")
            != made_at.tz_convert("UTC").floor("min") + pd.Timedelta(minutes=horizon)
        ):
            raise DetectorUnavailable("backend returned invalid forecast timestamps")
        upper = 100.0 if metric.startswith(("loss_pct_", "iface_util_pct_")) else None
        if (
            not np.isfinite([low, median, high]).all()
            or not low <= median <= high
            or low < 0
            or (upper is not None and high > upper)
        ):
            raise DetectorUnavailable("backend returned invalid forecast quantiles")


def _empty_result(site_id: str, at: pd.Timestamp, provenance: str, status: str) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "as_of": at.isoformat(),
        "is_anomaly": None,
        "anomaly_score": None,
        "threshold": None,
        "cause": None,
        "cause_confidence": 0.0,
        "forecasts": [],
        "evidence": [],
        "status": status,
        "provenance": provenance,
        "supplemental_used": False,
        "availability": "unavailable",
    }


def detect(site_id: str, window: MetricsWindow, history: MetricsWindow) -> DetectionResult:
    """Run detection on one site's observations and return the shared core contract."""
    if not isinstance(window, MetricsWindow) or not isinstance(history, MetricsWindow):
        raise DetectorUnavailable("detect requires core MetricsWindow inputs")
    if window.probe_metrics.empty or window.iface_metrics.empty:
        raise DetectorUnavailable("probe and interface observations are required")
    if not window.probe_metrics["site_id"].eq(site_id).all() or not window.iface_metrics[
        "site_id"
    ].eq(site_id).all():
        raise DetectorUnavailable("metrics window contains rows for a different site")

    # Prior history is context only. It supplies observations, never labels or expected causes.
    probes = _combine_observations(history.probe_metrics, window.probe_metrics)
    interfaces = _combine_observations(history.iface_metrics, window.iface_metrics)
    target_roles = _identity_target_roles(probes)
    settings = Settings()
    from netcortex_detector import providers
    from netcortex_detector.preparation import get_prepared_detector

    prepared = get_prepared_detector()
    if prepared is None:
        token = settings.tabpfn_token.get_secret_value() if settings.tabpfn_token else None
        backend = providers.TabPFNBackend(
            settings.tabpfn_mode, access_token=token, timeout_s=settings.http_timeout_s
        )
        if not str(getattr(backend, "provenance", "")).startswith("fixture:"):
            raise DetectorUnavailable(
                "public detect requires configure_detector() before real provider inference"
            )
        threshold = None
    else:
        backend, threshold = prepared
        if backend.mode != settings.tabpfn_mode:
            raise DetectorUnavailable("prepared detector mode does not match current Settings")
    result = run_engine(
        probes,
        interfaces,
        site_id=site_id,
        as_of=window.as_of,
        backend=backend,
        config=DetectorConfig(target_roles=target_roles),
        anomaly_threshold=threshold,
    )
    if result["availability"] != "available":
        raise DetectorUnavailable(f"detector data unavailable ({result['status']})")

    grouped: dict[str, list[ForecastPoint]] = {}
    for row in result["forecasts"]:
        metric = row["metric"]
        key = _forecast_series_key(metric)
        grouped.setdefault(key, []).append(
            ForecastPoint(
                time=pd.Timestamp(row["target_time"]).to_pydatetime(),
                p10=row["p10"],
                p50=row["p50"],
                p90=row["p90"],
            )
        )
    series = [
        SeriesForecast(series_key=key, points=sorted(points, key=lambda point: point.time))
        for key, points in sorted(grouped.items())
    ]
    provenance = str(result["provenance"])
    is_fixture = provenance.startswith("fixture:")
    mode = "mock" if is_fixture else settings.tabpfn_mode
    model = "fixture_persistence" if is_fixture else backend.provenance
    return DetectionResult(
        is_anomaly=result["is_anomaly"],
        score=result["anomaly_score"],
        cause_guess=Cause(result["cause"]),
        cause_confidence=result["cause_confidence"],
        evidence=result["evidence"],
        series=series,
        model=model,
        mode=mode,
    )


def _forecast_series_key(metric: str) -> str:
    """Map a raw feature metric to the matching shared core series key."""
    for prefix, kind, field, role_prefix in (
        ("rtt_ms_", "probe", "rtt_ms", "target:"),
        ("loss_pct_", "probe", "loss_pct", "target:"),
        ("iface_util_pct_", "iface", "util_pct", "interface:"),
    ):
        if metric.startswith(prefix):
            name = metric.removeprefix(prefix).removeprefix(role_prefix)
            if not name:
                break
            return series_key(kind, name, field)
    raise DetectorUnavailable("backend forecast metric cannot be mapped to a core series")


def _combine_observations(history: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in (history, current) if not frame.empty]
    if not frames:
        return current.copy()
    combined = pd.concat(frames, ignore_index=True).drop_duplicates(keep="last")
    return combined


def _identity_target_roles(probes: pd.DataFrame) -> dict[str, str]:
    """Keep each observed target name intact when building feature columns."""
    return {
        str(target): str(target)
        for target in probes.get("target", pd.Series(dtype=str)).dropna().unique()
    }


def fingerprint(frame: pd.DataFrame) -> str:
    """Stable small-input cache key, excluding caller-owned object identity."""
    payload = pd.util.hash_pandas_object(frame, index=True).values.tobytes()
    return hashlib.sha256(payload).hexdigest()
