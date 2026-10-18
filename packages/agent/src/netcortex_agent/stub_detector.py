"""Rule-based stand-in for packages/detector (TabPFN) until it merges. Same interface:
detect(site_id, window, history) -> DetectionResult, with mode="mock".

It compares the last 3 minutes with the rest of the window and history, and checks the
rules in order: uplink down, DNS slow, heavy user, uplink congestion, upstream degradation.
Forecast bands are the baseline's p10/p50/p90, held flat for the next 5 minutes.
"""

import ipaddress
from datetime import timedelta

import pandas as pd
from netcortex_core import (
    Cause,
    DetectionResult,
    ForecastPoint,
    MetricsWindow,
    ModuleUnavailable,
    SeriesForecast,
    series_key,
)

MODEL = "rules-v0"
RECENT = timedelta(minutes=3)
LATEST = timedelta(minutes=1)  # outages show up in the newest minute first


def _public(target: str) -> bool:
    try:
        return not ipaddress.ip_address(target).is_private
    except ValueError:
        return False


def _split(frame: pd.DataFrame, as_of) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame, frame
    times = pd.to_datetime(frame["time"], utc=True)
    return frame[times > as_of - RECENT], frame[times <= as_of - RECENT]


def _stat(frame: pd.DataFrame, column: str, name_col: str, name: str, how: str = "median"):
    values = pd.to_numeric(frame.loc[frame[name_col] == name, column], errors="coerce").dropna()
    return None if values.empty else float(getattr(values, how)())


def _forecast(baseline: pd.DataFrame, name_col: str, name: str, column: str, kind: str, as_of):
    values = pd.to_numeric(
        baseline.loc[baseline[name_col] == name, column], errors="coerce"
    ).dropna()
    if len(values) < 3:
        return None
    p10, p50, p90 = (float(values.quantile(q)) for q in (0.1, 0.5, 0.9))
    points = [
        ForecastPoint(time=as_of + timedelta(minutes=m), p10=p10, p50=p50, p90=max(p90, p50))
        for m in range(1, 6)
    ]
    return SeriesForecast(series_key=series_key(kind, name, column), points=points)


def detect(site_id: str, window: MetricsWindow, history: MetricsWindow) -> DetectionResult:
    as_of = window.as_of
    probes = pd.concat([history.probe_metrics, window.probe_metrics], ignore_index=True)
    if window.probe_metrics.empty:
        raise ModuleUnavailable(f"no probe data for {site_id}")
    ifaces = pd.concat([history.iface_metrics, window.iface_metrics], ignore_index=True)
    subs = pd.concat([history.subscriber_metrics, window.subscriber_metrics], ignore_index=True)
    recent_p, base_p = _split(probes, as_of)
    recent_i, base_i = _split(ifaces, as_of)
    recent_s, base_s = _split(subs, as_of)

    icmp_targets = sorted(set(probes.loc[probes["kind"] == "icmp", "target"]))
    public = [t for t in icmp_targets if _public(t)]
    private = [t for t in icmp_targets if not _public(t)]
    dns_targets = sorted(set(probes.loc[probes["kind"] == "dns", "target"]))

    def rtt_ratio(target: str) -> float:
        now = _stat(recent_p, "rtt_ms", "target", target)
        before = _stat(base_p, "rtt_ms", "target", target)
        return (now / before) if now and before else 1.0

    def series(*specs) -> list[SeriesForecast]:
        made = [_forecast(*spec, as_of) for spec in specs]
        return [s for s in made if s is not None]

    cause, evidence, forecasts = Cause.NORMAL, [], []
    latest_p = recent_p[pd.to_datetime(recent_p["time"], utc=True) > as_of - LATEST]
    loss = {t: _stat(latest_p, "loss_pct", "target", t, "mean") or 0.0 for t in public}

    # 1. Uplink down: outside targets unreachable, gateway fine.
    if public and all(value >= 80 for value in loss.values()):
        gateway_ok = [
            t for t in private if (_stat(recent_p, "loss_pct", "target", t, "mean") or 0) < 50
        ]
        cause = Cause.UPLINK_DOWN
        evidence.append(f"{min(loss.values()):.0f}% loss to {', '.join(public)} in the last minute")
        if gateway_ok:
            rtt = _stat(recent_p, "rtt_ms", "target", gateway_ok[0]) or 0
            evidence.append(f"gateway {gateway_ok[0]} still answers in {rtt:.0f} ms")
        forecasts = series((base_p, "target", public[0], "loss_pct", "probe"))

    # 2. DNS slow: one resolver slow or failing while pings are normal.
    if cause is Cause.NORMAL:
        for target in dns_targets:
            now = _stat(recent_p, "rtt_ms", "target", target)
            before = _stat(base_p, "rtt_ms", "target", target)
            failing = _stat(recent_p, "loss_pct", "target", target, "mean") or 0
            slow = now is not None and before is not None and now >= max(3 * before, 100)
            pings_ok = all(
                rtt_ratio(t) < 2 and (_stat(recent_p, "loss_pct", "target", t, "mean") or 0) < 10
                for t in public
            )
            if (slow or failing >= 20) and pings_ok:
                cause = Cause.DNS_SLOW
                evidence.append(
                    f"DNS lookups via {target.removeprefix('dns:')} take {now or 0:.0f} ms "
                    f"(normally {before or 0:.0f} ms); {failing:.0f}% fail"
                )
                evidence.append("ping latency to outside targets is normal")
                forecasts = series((base_p, "target", target, "rtt_ms", "probe"))
                break

    # 3. Heavy user: one subscriber far above its usual rate, filling the uplink.
    uplink_util = _stat(recent_i, "util_pct", "iface", "ether1", "mean")
    if cause is Cause.NORMAL and not recent_s.empty:
        total = pd.to_numeric(recent_s["rx_bps"]).sum()
        for ip in sorted(set(recent_s["ip"])):
            now = _stat(recent_s, "rx_bps", "ip", ip, "mean") or 0
            before = _stat(base_s, "rx_bps", "ip", ip) or 0
            share = (
                (pd.to_numeric(recent_s.loc[recent_s["ip"] == ip, "rx_bps"]).sum() / total)
                if total
                else 0
            )
            if now >= max(5 * before, 20e6) and share >= 0.3:
                cause = Cause.HEAVY_USER
                evidence.append(
                    f"subscriber {ip} downloading {now / 1e6:.0f} Mbit/s "
                    f"(usually {before / 1e6:.0f})"
                )
                if uplink_util is not None:
                    evidence.append(f"uplink ether1 at {uplink_util:.0f}% for 3 min")
                slow = [t for t in public if rtt_ratio(t) >= 2]
                if slow:
                    evidence.append(f"latency to {slow[0]} up {rtt_ratio(slow[0]):.1f}x")
                forecasts = series(
                    (base_p, "target", (slow or public or icmp_targets)[0], "rtt_ms", "probe"),
                    (base_i, "iface", "ether1", "util_pct", "iface"),
                )
                break

    # 4. Uplink congestion: the uplink is full without one heavy user.
    if cause is Cause.NORMAL and uplink_util is not None and uplink_util >= 90:
        cause = Cause.UPLINK_CONGESTION
        evidence.append(f"uplink ether1 at {uplink_util:.0f}% for 3 min, spread across users")
        forecasts = series((base_i, "iface", "ether1", "util_pct", "iface"))

    # 5. Upstream degradation: every outside target slow, gateway fine.
    if cause is Cause.NORMAL and public and all(rtt_ratio(t) >= 3 for t in public):
        cause = Cause.UPSTREAM_DEGRADATION
        evidence.append(
            f"latency to {', '.join(public)} up "
            f"{min(rtt_ratio(t) for t in public):.1f}x; gateway normal"
        )
        forecasts = series((base_p, "target", public[0], "rtt_ms", "probe"))

    anomaly = cause is not Cause.NORMAL
    if not forecasts and public:
        forecasts = series((base_p, "target", public[0], "rtt_ms", "probe"))
    return DetectionResult(
        is_anomaly=anomaly,
        score=0.9 if anomaly else 0.1,
        series=forecasts,
        cause_guess=cause,
        cause_confidence=0.75 if anomaly else 0.9,
        evidence=evidence,
        model=MODEL,
        mode="mock",
    )
