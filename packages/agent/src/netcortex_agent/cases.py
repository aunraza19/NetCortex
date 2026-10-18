"""Three hand-made incidents for the live smoke test and the thinking on/off comparison.

Each has a small site, a 30-minute window (one row per minute, incident in the last 8
minutes) and the detection a detector might produce. These are fixtures, not data: real
evaluation uses the simulator's cases in eval/.
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from netcortex_core import (
    Cause,
    DetectionResult,
    ForecastPoint,
    MetricsWindow,
    ProbeTarget,
    SeriesForecast,
    Site,
    TargetRole,
    TemplateId,
    Uplink,
    UplinkRole,
)

AS_OF = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)  # 20:00 in Pakistan, evening peak
MINUTES = 30
INCIDENT_MINUTES = 8

SITE = Site(
    id="north-tower",
    name="North Tower",
    subscribers=120,
    uplinks=[
        Uplink(iface="ether1", role=UplinkRole.PRIMARY, capacity_mbps=180, gateway="10.10.0.1"),
        Uplink(iface="ether2", role=UplinkRole.BACKUP, capacity_mbps=80, gateway="10.20.0.1"),
    ],
    targets=[
        ProbeTarget(key="10.0.0.1", host="10.0.0.1", role=TargetRole.GATEWAY),
        ProbeTarget(key="1.1.1.1", host="1.1.1.1", role=TargetRole.PUBLIC_DNS),
        ProbeTarget(key="8.8.8.8", host="8.8.8.8", role=TargetRole.PUBLIC_DNS),
        ProbeTarget(
            key="dns:203.0.113.53", host="203.0.113.53", kind="dns", role=TargetRole.PUBLIC_DNS
        ),
        ProbeTarget(key="dns:1.1.1.1", host="1.1.1.1", kind="dns", role=TargetRole.PUBLIC_DNS),
    ],
)  # fmt: skip

PROBES = {"10.0.0.1": 2.0, "1.1.1.1": 18.0, "8.8.8.8": 25.0}  # normal ICMP RTT, ms
DNS = {"dns:203.0.113.53": 22.0, "dns:1.1.1.1": 12.0}  # normal lookup time, ms (router uses .53)
SUBSCRIBERS = {"10.0.0.42": 4.0, "10.0.0.57": 3.0, "10.0.0.63": 2.5}  # normal Mbit/s


@dataclass
class Case:
    name: str
    site: Site
    window: MetricsWindow
    detection: DetectionResult
    expected_cause: Cause
    expected_template: TemplateId
    expected_params: dict[str, Any] = field(default_factory=dict)  # key params to check


def _times() -> list[datetime]:
    return [AS_OF - timedelta(minutes=MINUTES - 1 - i) for i in range(MINUTES)]


def _wobble(i: int, base: float, pct: float = 0.05) -> float:
    """Small deterministic variation so normal data isn't flat."""
    return base * (1 + pct * math.sin(i * 1.7))


def _window(
    rtt: dict[str, float | None] | None = None,
    loss: dict[str, float] | None = None,
    util: dict[str, float] | None = None,
    subscriber_mbps: dict[str, float] | None = None,
) -> MetricsWindow:
    """Normal data, with the given values replacing it during the incident minutes."""
    rtt, loss, util, subscriber_mbps = rtt or {}, loss or {}, util or {}, subscriber_mbps or {}
    probe_rows, iface_rows, sub_rows = [], [], []
    for i, time in enumerate(_times()):
        incident = i >= MINUTES - INCIDENT_MINUTES
        for target, normal in {**PROBES, **DNS}.items():
            value = rtt.get(target, normal) if incident else normal
            probe_rows.append({
                "time": time, "site_id": SITE.id, "target": target,
                "kind": "dns" if target.startswith("dns:") else "icmp",
                "rtt_ms": None if value is None else _wobble(i, value),
                "jitter_ms": None if value is None else _wobble(i, value * 0.1),
                "loss_pct": loss.get(target, 0.0) if incident else 0.0, "source": "sim",
            })  # fmt: skip
        for iface, normal_util, capacity in (("ether1", 55.0, 180), ("ether2", 1.0, 80)):
            pct = util.get(iface, normal_util) if incident else normal_util
            bps = int(_wobble(i, pct) / 100 * capacity * 1_000_000)
            iface_rows.append({
                "time": time, "site_id": SITE.id, "iface": iface, "rx_bps": bps,
                "tx_bps": bps // 8, "util_pct": _wobble(i, pct), "drops": 0, "errors": 0,
                "source": "sim",
            })  # fmt: skip
        for ip, normal_mbps in SUBSCRIBERS.items():
            mbps = subscriber_mbps.get(ip, normal_mbps) if incident else normal_mbps
            sub_rows.append({
                "time": time, "site_id": SITE.id, "ip": ip,
                "rx_bps": int(_wobble(i, mbps) * 1_000_000), "tx_bps": int(mbps * 100_000),
                "source": "sim",
            })  # fmt: skip
    return MetricsWindow(
        as_of=AS_OF,
        probe_metrics=pd.DataFrame(probe_rows),
        iface_metrics=pd.DataFrame(iface_rows),
        subscriber_metrics=pd.DataFrame(sub_rows),
    )


def _forecast(series: str, p50: float) -> SeriesForecast:
    points = [
        ForecastPoint(time=AS_OF + timedelta(minutes=m), p10=p50 * 0.8, p50=p50, p90=p50 * 1.3)
        for m in range(1, 6)
    ]
    return SeriesForecast(series_key=series, points=points)


def _detection(
    cause: Cause, confidence: float, evidence: list[str], series: list
) -> DetectionResult:
    return DetectionResult(
        is_anomaly=True, score=0.93, series=series, cause_guess=cause,
        cause_confidence=confidence, evidence=evidence, model="hand-made", mode="mock",
    )  # fmt: skip


def heavy_user() -> Case:
    return Case(
        name="heavy_user",
        site=SITE,
        window=_window(
            rtt={"1.1.1.1": 95.0, "8.8.8.8": 140.0},
            util={"ether1": 97.0},
            subscriber_mbps={"10.0.0.42": 140.0},
        ),
        detection=_detection(
            Cause.HEAVY_USER,
            0.62,
            [
                "uplink ether1 at 97% for 8 min",
                "one subscriber's download jumped to about 140 Mbit/s",
                "8.8.8.8 latency 140 ms, forecast 25 ms",
            ],
            [_forecast("probe:8.8.8.8:rtt_ms", 25.0), _forecast("iface:ether1:util_pct", 55.0)],
        ),
        expected_cause=Cause.HEAVY_USER,
        expected_template=TemplateId.QUEUE_LIMIT,
        expected_params={"target": "10.0.0.42"},
    )


def uplink_down() -> Case:
    return Case(
        name="uplink_down",
        site=SITE,
        window=_window(
            rtt={"1.1.1.1": None, "8.8.8.8": None, "dns:203.0.113.53": None, "dns:1.1.1.1": None},
            loss={
                "1.1.1.1": 100.0,
                "8.8.8.8": 100.0,
                "dns:203.0.113.53": 100.0,
                "dns:1.1.1.1": 100.0,
            },
            util={"ether1": 0.0},
        ),  # fmt: skip
        detection=_detection(
            Cause.UPLINK_DOWN,
            0.81,
            [
                "100% loss to 1.1.1.1 and 8.8.8.8 for 8 min",
                "gateway 10.0.0.1 still answers in 2 ms",
                "ether1 traffic dropped to 0",
            ],
            [_forecast("probe:1.1.1.1:loss_pct", 0.5), _forecast("iface:ether1:util_pct", 55.0)],
        ),
        expected_cause=Cause.UPLINK_DOWN,
        expected_template=TemplateId.FAILOVER_ROUTE,
        expected_params={"primary_gateway": "10.10.0.1", "backup_gateway": "10.20.0.1"},
    )


def dns_slow() -> Case:
    return Case(
        name="dns_slow",
        site=SITE,
        window=_window(rtt={"dns:203.0.113.53": 650.0}, loss={"dns:203.0.113.53": 20.0}),
        detection=_detection(
            Cause.DNS_SLOW,
            0.74,
            [
                "DNS lookups via 203.0.113.53 take 650 ms, forecast 22 ms; 20% fail",
                "DNS via 1.1.1.1 normal at 12 ms",
                "ping latency to all targets normal",
            ],
            [_forecast("probe:dns:203.0.113.53:rtt_ms", 22.0)],
        ),
        expected_cause=Cause.DNS_SLOW,
        expected_template=TemplateId.DNS_SERVERS,
        expected_params={},  # any valid resolver list that drops 203.0.113.53
    )


def all_cases() -> list[Case]:
    return [heavy_user(), uplink_down(), dns_slow()]
