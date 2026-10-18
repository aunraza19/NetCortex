"""Plain functions that turn the detection, metrics window and site into small facts for
the model. Kept free of model code so they're easy to test.
"""

import ipaddress
from datetime import timedelta
from typing import Any

import pandas as pd
from netcortex_core import DetectionResult, MetricsWindow, Site, parse_series_key

# Which frame and name column each series kind reads, and its metrics.
_SERIES = {
    "probe": ("probe_metrics", "target", ("rtt_ms", "jitter_ms", "loss_pct")),
    "iface": ("iface_metrics", "iface", ("util_pct", "rx_bps", "tx_bps", "drops", "errors")),
    "subscriber": ("subscriber_metrics", "ip", ("rx_bps", "tx_bps")),
}
MAX_POINTS = 10


def available_series(window: MetricsWindow) -> dict[str, list[str]]:
    """{series kind: names present in the window}, e.g. {"probe": ["1.1.1.1", ...]}."""
    found = {}
    for kind, (frame_name, column, _) in _SERIES.items():
        names = sorted(getattr(window, frame_name)[column].dropna().astype(str).unique())
        if names:
            found[kind] = names
    return found


def metric_summary(window: MetricsWindow, series: str, minutes: int) -> dict[str, Any]:
    """Latest, mean, min, max and up to 10 evenly spaced points of one series."""
    try:
        kind, name, metric = parse_series_key(series)
    except ValueError:
        return {"error": f"{series!r} is not a series key like 'probe:8.8.8.8:rtt_ms'"}
    frame_name, column, metrics = _SERIES[kind]
    if metric not in metrics:
        return {"error": f"{kind} series have metrics {list(metrics)}, not {metric!r}"}
    frame = getattr(window, frame_name)
    since = window.as_of - timedelta(minutes=max(1, minutes))
    times = pd.to_datetime(frame["time"], utc=True)
    rows = frame[(frame[column].astype(str) == name) & (times >= since)]
    values = pd.Series(rows[metric].to_numpy(dtype=float), index=times[rows.index]).sort_index()
    measured = values.dropna()
    if values.empty:
        return {"error": f"no data for {series!r}", "available": available_series(window)}
    step = max(1, len(values) // MAX_POINTS)
    points = [
        [time.strftime("%H:%M"), None if pd.isna(value) else round(float(value), 2)]
        for time, value in values.iloc[::-step][::-1].items()
    ]
    summary: dict[str, Any] = {"series": series, "minutes": minutes, "points": points}
    if measured.empty:
        summary["note"] = "no measured values (for rtt_ms this means every probe was lost)"
    else:
        summary |= {
            "latest": round(float(measured.iloc[-1]), 2),
            "mean": round(float(measured.mean()), 2),
            "min": round(float(measured.min()), 2),
            "max": round(float(measured.max()), 2),
        }
    return summary


def subscriber_rates(window: MetricsWindow, target: str) -> dict[str, float]:
    """Current download/upload Mbit/s of an IP or subnet: the latest row of each matching IP.

    Empty when the window has no subscriber data for the target.
    """
    network = ipaddress.ip_network(target, strict=False)
    frame = window.subscriber_metrics
    if frame.empty:
        return {}
    in_target = frame["ip"].astype(str).map(lambda ip: ipaddress.ip_address(ip) in network)
    rows = frame[in_target]
    if rows.empty:
        return {}
    latest = rows.assign(_t=pd.to_datetime(rows["time"], utc=True)).sort_values("_t")
    latest = latest.groupby("ip").tail(1)
    return {
        "current_download_mbps": float(latest["rx_bps"].sum()) / 1e6,
        "current_upload_mbps": float(latest["tx_bps"].sum()) / 1e6,
    }


def forecast_summary(detection: DetectionResult, series: str) -> dict[str, Any]:
    for forecast in detection.series:
        if forecast.series_key == series:
            return {
                "series": series,
                "points": [
                    {"time": p.time.strftime("%H:%M"), "p10": p.p10, "p50": p.p50, "p90": p.p90}
                    for p in forecast.points
                ],
            }
    return {
        "error": f"no forecast for {series!r}",
        "forecasts_exist_for": [f.series_key for f in detection.series],
    }


def describe_site(site: Site | None, site_id: str) -> str:
    if site is None:
        return f"Site {site_id} (no layout on record)."
    uplinks = "; ".join(
        f"{u.iface} {u.role.value}"
        + (f" {u.capacity_mbps:g} Mbit/s" if u.capacity_mbps else "")
        + (f" gateway {u.gateway}" if u.gateway else "")
        for u in site.uplinks
    )
    return (
        f"Site {site.name} ({site.id}), {site.subscribers} subscribers. "
        f"Uplinks: {uplinks or 'unknown'}."
    )


def build_prompt(
    site_id: str, site: Site | None, detection: DetectionResult, window: MetricsWindow
) -> str:
    series = available_series(window)
    metrics = {kind: _SERIES[kind][2] for kind in series}
    lines = [
        describe_site(site, site_id),
        f"Detection at {window.as_of:%Y-%m-%d %H:%M} UTC, anomaly score {detection.score:.2f}.",
        f"Detector's cause guess: {detection.cause_guess.value} "
        f"(confidence {detection.cause_confidence:.2f}).",
        "Evidence:",
        *(f"- {item}" for item in detection.evidence),
        "Series you can query (series key = kind:name:metric):",
        *(
            f"- {kind}:<name>:{{{','.join(metrics[kind])}}} for names {names}"
            for kind, names in series.items()
        ),
        "Investigate, then return the incident report.",
    ]
    return "\n".join(lines)
