from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from netcortex_core import (
    Cause,
    IfaceMetric,
    ModuleUnavailable,
    ProbeKind,
    ProbeMetric,
    ProbeTarget,
    ScenarioLabel,
    Site,
    Source,
    SubscriberMetric,
    TargetRole,
    TemplateId,
    Uplink,
    UplinkRole,
)
from netcortex_core import db as core_db
from netcortex_core.settings import Settings
from psycopg.types.json import Jsonb


def _find_workspace_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "data/sites.yaml").is_file():
            return parent
    return Path.cwd()


ROOT = _find_workspace_root()
CAUSES = (
    "uplink_congestion",
    "heavy_user",
    "upstream_degradation",
    "game_route_issue",
    "wireless_interference",
    "uplink_down",
    "dns_slow",
)
TEMPLATES = {
    "uplink_congestion": "priority_queue",
    "heavy_user": "queue_limit",
    "upstream_degradation": "none",
    "game_route_issue": "none",
    "wireless_interference": "none",
    "uplink_down": "failover_route",
    "dns_slow": "dns_servers",
}
TARGETS = ("gateway", "upstream-hop", "1.1.1.1", "8.8.8.8", "regional-game")
PUBLIC_DNS_TARGETS = frozenset({"1.1.1.1", "8.8.8.8"})
DEFAULT_BASELINES = {
    "gateway": 1.8,
    "upstream-hop": 8.0,
    "1.1.1.1": 28.0,
    "8.8.8.8": 35.0,
    "regional-game": 42.0,
}
DEFAULT_JITTER_MS = 1.0


def sites() -> dict[str, Any]:
    path = ROOT / "data/sites.yaml"
    if path.is_file():
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    with files("netcortex_simgen").joinpath("resources/sites.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    return value.astimezone(UTC)


def _baseline_profiles() -> tuple[
    dict[str, dict[str, float]],
    dict[str, dict[int, dict[str, float]]],
    dict[str, Any],
]:
    """Resolve exact target calibration and explicitly enabled DNS role proxies."""
    path = ROOT / "data/calibration.json"
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}

    target_medians = payload.get("target_medians_ms", {})
    exact_hourly = payload.get("target_hourly_stats", {})
    exact_hourly_rtt = payload.get("target_hourly_ms", {})
    role_proxy = payload.get("role_proxy", {})
    role_medians = payload.get("role_medians", {})
    role_hourly = payload.get("role_hourly_stats", {})
    profiles = {
        target: {
            "rtt_ms": DEFAULT_BASELINES[target],
            "jitter_ms": DEFAULT_JITTER_MS,
            "loss_pct": 0.0,
        }
        for target in TARGETS
    }
    hourly: dict[str, dict[int, dict[str, float]]] = {}
    exact_targets: set[str] = set()

    for target in TARGETS:
        median = target_medians.get(target)
        if isinstance(median, (float, int)):
            profiles[target]["rtt_ms"] = float(median)
            exact_targets.add(target)
        target_stats = payload.get("target_stats", {}).get(target, {})
        if isinstance(target_stats, dict):
            for metric in ("rtt_ms", "jitter_ms", "loss_pct"):
                if isinstance(target_stats.get(metric), (float, int)):
                    profiles[target][metric] = float(target_stats[metric])
                    exact_targets.add(target)
        hourly[target] = {}
        for hour, stats in exact_hourly.get(target, {}).items():
            if not isinstance(stats, dict):
                continue
            values = {
                metric: float(stats[metric])
                for metric in ("rtt_ms", "jitter_ms", "loss_pct")
                if isinstance(stats.get(metric), (float, int))
            }
            if values:
                hourly[target][int(hour)] = values
                exact_targets.add(target)
        for hour, value in exact_hourly_rtt.get(target, {}).items():
            if isinstance(value, (float, int)):
                hourly[target].setdefault(int(hour), {})["rtt_ms"] = float(value)
                exact_targets.add(target)

    configured_source_targets = role_proxy.get("source_targets", [])
    target_roles = payload.get("target_roles", {})
    verified_source_targets = [
        target
        for target in configured_source_targets
        if isinstance(target, str) and target_roles.get(target) == "public_dns_reachability_proxy"
    ]
    explicit_proxy = (
        role_proxy.get("enabled") is True
        and role_proxy.get("role") == "public_dns_reachability_proxy"
        and bool(verified_source_targets)
    )
    applied_targets: list[str] = []
    source_targets = verified_source_targets if explicit_proxy else []
    proxy_role = "public_dns_reachability_proxy"
    role_median = role_medians.get(proxy_role, {}) if explicit_proxy else {}
    role_hours = role_hourly.get(proxy_role, {}) if explicit_proxy else {}
    if explicit_proxy and isinstance(role_median, dict):
        for target in sorted(PUBLIC_DNS_TARGETS):
            if target in exact_targets:
                continue
            if isinstance(role_median.get("rtt_ms"), (float, int)):
                profiles[target]["rtt_ms"] = float(role_median["rtt_ms"])
                for metric in ("jitter_ms", "loss_pct"):
                    if isinstance(role_median.get(metric), (float, int)):
                        profiles[target][metric] = float(role_median[metric])
                if isinstance(role_hours, dict):
                    hourly[target] = {}
                    for hour, stats in role_hours.items():
                        if isinstance(stats, dict):
                            hourly[target][int(hour)] = {
                                metric: float(stats[metric])
                                for metric in ("rtt_ms", "jitter_ms", "loss_pct")
                                if isinstance(stats.get(metric), (float, int))
                            }
                applied_targets.append(target)

    modes = {
        target: (
            "exact_target"
            if target in exact_targets
            else "explicit_role_proxy"
            if target in applied_targets
            else "illustrative_default"
        )
        for target in TARGETS
    }
    proxy_uncertainty = role_proxy.get(
        "uncertainty",
        "A public root-DNS-server route is not proven equivalent to configured DNS destinations.",
    )
    metadata = {
        "calibration_source": payload.get("provenance", ["built-in illustrative defaults"]),
        "target_modes": modes,
        "role_proxy": {
            "enabled": bool(applied_targets),
            "role": proxy_role if applied_targets else None,
            "source_targets": source_targets if applied_targets else [],
            "applied_to": applied_targets,
            "uncertainty": proxy_uncertainty if applied_targets else None,
        },
    }
    return profiles, hourly, metadata


def _baselines() -> tuple[dict[str, float], dict[str, dict[int, float]], str]:
    """Compatibility helper exposing RTT baselines and provenance summary."""
    profiles, hourly_profiles, metadata = _baseline_profiles()
    rtt = {target: profile["rtt_ms"] for target, profile in profiles.items()}
    hourly = {
        target: {hour: stats["rtt_ms"] for hour, stats in values.items() if "rtt_ms" in stats}
        for target, values in hourly_profiles.items()
    }
    proxy = metadata["role_proxy"]
    source = ", ".join(metadata["calibration_source"])
    if proxy["enabled"]:
        source += (
            "; explicit role proxy from "
            + ", ".join(proxy["source_targets"])
            + " to "
            + ", ".join(proxy["applied_to"])
        )
    return rtt, hourly, source


def _labels(
    selected: list[dict[str, Any]],
    start: datetime,
    days: int,
    seed: int,
    scenario_type: str | None,
    normal_only: bool,
    duration_min: int,
) -> list[dict[str, Any]]:
    if normal_only:
        return []
    if scenario_type:
        causes = [scenario_type]
    else:
        # A normal seven-day fixture includes all seven scenarios once/site.
        causes = list(CAUSES)
    out = []
    for site_index, site in enumerate(selected):
        for cause_index, cause in enumerate(causes):
            # Events are far enough apart to preserve distinct recovery windows.
            at = start + timedelta(hours=2 + cause_index * 2, minutes=site_index * 25)
            out.append(
                _label(
                    site,
                    cause,
                    at,
                    at + timedelta(minutes=duration_min),
                    seed + site_index * 10_000 + cause_index,
                )
            )
    return out


def generate(
    days: int = 1,
    seed: int = 42,
    start: datetime | None = None,
    scenario_type: str | None = None,
    duration_min: int = 15,
    site_id: str | None = None,
    normal_only: bool = False,
    hours: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Generate repeatable UTC table-shaped observations and plain fixture labels.

    `hours` can limit a case window (1..24*days); the default emits full days.
    Unless `normal_only` or one `scenario_type` is provided, every cause is
    scheduled once per selected site within the first day.
    """
    if (
        days < 1
        or days > 30
        or duration_min < 1
        or (hours is not None and not 1 <= hours <= days * 24)
    ):
        raise ValueError(
            "days must be 1..30, duration_min positive, and hours within requested days"
        )
    if scenario_type is not None and scenario_type not in CAUSES:
        raise ValueError(f"unsupported scenario: {scenario_type}")
    layout = sites()["sites"]
    selected = (
        [s for s in layout if s["id"] == site_id]
        if site_id is not None
        else [s for s in layout if not s.get("runtime_only")]
    )
    if not selected:
        raise ValueError(f"unknown site: {site_id}")
    start = _utc(start or datetime(2026, 10, 12, tzinfo=UTC))
    num_hours = hours or days * 24
    num_pings = num_hours * 60 * 6
    num_interfaces = num_hours * 60 * 2
    labels = _labels(selected, start, days, seed, scenario_type, normal_only, duration_min)
    baseline_profiles, hourly_profiles, calibration_metadata = _baseline_profiles()
    rng = np.random.default_rng(seed)
    pings: list[pd.DataFrame] = []
    ifaces: list[dict[str, Any]] = []
    for site in selected:
        times = pd.date_range(start=start, periods=num_pings, freq="10s", tz="UTC")
        local = times.tz_convert("Asia/Karachi")
        hour = (local.hour + local.minute / 60).to_numpy()
        weekend = np.asarray(local.dayofweek >= 5)
        daily = (
            0.12
            + 0.70 * np.exp(-0.5 * ((hour - 21.5) / 4.4) ** 2)
            + 0.24 * np.exp(-0.5 * ((hour - 1) / 2.0) ** 2)
        )
        daily *= np.where(weekend, 1.12, 1.0)
        capacity = float(site["uplinks"][0]["capacity_mbps"])
        subs = int(site["subscribers"])
        heavy = rng.uniform(1.2, 2.2)
        demand = (subs * (0.10 + daily * 0.28) * heavy / 1.9) * (
            1 + rng.normal(0, 0.055, num_pings)
        )
        util = np.clip(demand / capacity * 100, 8, 94)
        cause_at_ping = np.full(num_pings, "", dtype=object)
        for label in labels:
            if label["site_id"] == site["id"]:
                cause_at_ping[(times >= label["start"]) & (times < label["end"])] = label["cause"]

        # Aggregate uplink effects and counters use the same event window as probes.
        itimes = pd.date_range(start=start, periods=num_interfaces, freq="30s", tz="UTC")
        for ix, stamp in enumerate(itimes):
            pi = min(ix * 3, num_pings - 1)
            cause = next(
                (
                    x["cause"]
                    for x in labels
                    if x["site_id"] == site["id"] and x["start"] <= stamp.to_pydatetime() < x["end"]
                ),
                "",
            )
            base_util = float(util[pi])
            up = (
                min(99.5, max(base_util, 98.2))
                if cause == "uplink_congestion"
                else min(94, max(base_util, 87.0))
                if cause == "heavy_user"
                else base_util
            )
            down = cause == "uplink_down"
            primary = site["uplinks"][0]
            wire_loss = cause == "wireless_interference"
            rx = 0 if down else int(capacity * 1_000_000 * up / 100 * rng.uniform(0.47, 0.61))
            tx = 0 if down else int(capacity * 1_000_000 * up / 100 - rx)
            drops = (
                0
                if down
                else int(max(0, up - 85) * rng.uniform(0.2, 1.0))
                + (int(rng.integers(12, 35)) if cause == "uplink_congestion" else 0)
            )
            ifaces.append(
                {
                    "time": stamp.to_pydatetime(),
                    "site_id": site["id"],
                    "iface": primary["interface"],
                    "rx_bps": rx,
                    "tx_bps": tx,
                    "util_pct": 0.0 if down else up,
                    "drops": drops,
                    "errors": 1 if down else 0,
                    "source": "sim",
                }
            )
            backup = site.get("backup_uplink")
            if backup:
                bu = min(65, up * 0.62) if down else 0.0
                brx = int(backup["capacity_mbps"] * 1_000_000 * bu / 100 * 0.55)
                ifaces.append(
                    {
                        "time": stamp.to_pydatetime(),
                        "site_id": site["id"],
                        "iface": backup["interface"],
                        "rx_bps": brx,
                        "tx_bps": max(0, int(backup["capacity_mbps"] * 1_000_000 * bu / 100 - brx)),
                        "util_pct": bu,
                        "drops": 0,
                        "errors": 0,
                        "source": "sim",
                    }
                )
            for bh_index, backhaul in enumerate(site.get("backhauls", [])):
                bh_util = float(np.clip(18 + base_util * 0.48 + rng.normal(0, 3), 3, 95))
                affected = wire_loss and bh_index == 0
                bh_rx = int(backhaul["capacity_mbps"] * 1_000_000 * bh_util / 100 * 0.52)
                ifaces.append(
                    {
                        "time": stamp.to_pydatetime(),
                        "site_id": site["id"],
                        "iface": backhaul["interface"],
                        "rx_bps": bh_rx,
                        "tx_bps": int(
                            backhaul["capacity_mbps"] * 1_000_000 * bh_util / 100 - bh_rx
                        ),
                        "util_pct": bh_util,
                        "drops": int(rng.integers(15, 50)) if affected else int(rng.integers(0, 2)),
                        "errors": int(rng.integers(2, 12)) if affected else 0,
                        "source": "sim",
                    }
                )

        for target in TARGETS:
            target_profile = baseline_profiles[target]
            per_hour = hourly_profiles.get(target, {})
            base = np.asarray(
                [
                    per_hour.get(int(h), {}).get("rtt_ms", target_profile["rtt_ms"])
                    for h in local.hour
                ],
                dtype=float,
            )
            base_jitter = np.asarray(
                [
                    per_hour.get(int(h), {}).get("jitter_ms", target_profile["jitter_ms"])
                    for h in local.hour
                ],
                dtype=float,
            )
            base_loss = np.asarray(
                [
                    per_hour.get(int(h), {}).get("loss_pct", target_profile["loss_pct"])
                    for h in local.hour
                ],
                dtype=float,
            )
            outside = target != "gateway"
            event_cong = (cause_at_ping == "uplink_congestion") & outside
            event_heavy = (cause_at_ping == "heavy_user") & outside
            event_upstream = (cause_at_ping == "upstream_degradation") & outside
            event_game = (cause_at_ping == "game_route_issue") & (target == "regional-game")
            event_wireless = (cause_at_ping == "wireless_interference") & outside
            event_down = (cause_at_ping == "uplink_down") & outside
            queue = (
                np.minimum(180.0, 0.11 * util / np.maximum(0.06, 1 - util / 100))
                if outside
                else np.full(num_pings, 0.0)
            )
            queue = (
                queue
                + event_cong * 75
                + event_heavy * 38
                + event_upstream * 95
                + event_game * 180
                + event_wireless * 8
            )
            jitter = (
                base_jitter + util * 0.025 + event_wireless * 26 + rng.normal(0, 0.35, num_pings)
            )
            loss = (
                np.maximum(base_loss, (util - 95) * 0.15)
                + event_cong * 7
                + event_heavy * 1.5
                + event_upstream * 4
                + event_game * 9
                + event_wireless * 5
            )
            loss = np.clip(loss + rng.normal(0, 0.1, num_pings), 0, 99.9)
            loss[event_down] = 100.0
            rtt = np.maximum(
                0.2,
                base + queue + rng.normal(0, 1.4 + np.maximum(0.1, jitter) * 0.3, num_pings),
            )
            rtt[event_down] = np.nan
            jitter[event_down] = np.nan
            # DNS resolution delay is a supplemental observation, not ICMP RTT.
            pings.append(
                pd.DataFrame(
                    {
                        "time": times,
                        "site_id": site["id"],
                        "target": target,
                        "kind": "icmp",
                        "rtt_ms": rtt,
                        "jitter_ms": np.maximum(0.1, jitter),
                        "loss_pct": loss,
                        "source": "sim",
                    }
                )
            )
        dns_ms = np.maximum(5, 24 + rng.normal(0, 2, num_pings))
        dns_mask = cause_at_ping == "dns_slow"
        dns_ms[dns_mask] = np.maximum(300, rng.normal(650, 35, int(dns_mask.sum())))
        pings.append(
            pd.DataFrame(
                {
                    "time": times,
                    "site_id": site["id"],
                    "target": "dns:1.1.1.1",
                    "kind": "dns",
                    "rtt_ms": dns_ms,
                    "jitter_ms": np.maximum(0.1, rng.normal(2, 0.4, num_pings)),
                    "loss_pct": np.zeros(num_pings),
                    "source": "sim",
                }
            )
        )
    probe_frame = pd.concat(pings, ignore_index=True)
    iface_frame = pd.DataFrame(ifaces)
    probe_frame.attrs["calibration"] = calibration_metadata
    iface_frame.attrs["calibration"] = calibration_metadata
    return probe_frame, iface_frame, labels


def generate_supplemental(
    labels: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    seed: int = 42,
    site_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Generate continuous synthetic DNS/subscriber/backhaul observations.

    Each selected site has healthy baseline rows throughout the case window.
    Labels only alter seeded distributions in their event interval, so the
    presence of supplemental rows never gives away the class.
    """
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise ValueError("supplemental end must follow start")
    layout = sites()["sites"]
    selected = [s for s in layout if site_ids is None or s["id"] in site_ids]
    times = pd.date_range(start=start, end=end, freq="30s", inclusive="left", tz="UTC")
    rows = []
    for site_index, site in enumerate(selected):
        rng = np.random.default_rng(seed + site_index * 997)
        local = times.tz_convert("Asia/Karachi")
        hour = (local.hour + local.minute / 60).to_numpy()
        demand_curve = 0.12 + 0.70 * np.exp(-0.5 * ((hour - 21.5) / 4.4) ** 2)
        active_events = [x for x in labels if x["site_id"] == site["id"]]
        for stamp, daily in zip(times, demand_curve, strict=True):
            instant = stamp.to_pydatetime()
            event = next(
                (x["cause"] for x in active_events if x["start"] <= instant < x["end"]),
                "",
            )
            for resolver, baseline in (("1.1.1.1", 24.0), ("8.8.8.8", 31.0)):
                dns_ms = max(5.0, baseline + rng.normal(0, 2.0))
                if event == "dns_slow":
                    dns_ms = max(300.0, rng.normal(650.0, 35.0))
                rows.append(
                    {
                        "time": instant,
                        "site_id": site["id"],
                        "kind": "dns_resolution",
                        "entity": resolver,
                        "latency_ms": float(dns_ms),
                        "loss_pct": 0.0,
                        "status": "synthetic experimental; core DNS timing contract pending",
                        "source": "sim_supplemental",
                    }
                )
            rx_mbps = max(0.05, rng.gamma(2.0, 0.9) * (0.6 + daily))
            if event == "heavy_user":
                rx_mbps = max(50.0, rng.normal(75.0, 6.0))
            rows.append(
                {
                    "time": instant,
                    "site_id": site["id"],
                    "kind": "subscriber_traffic",
                    "entity": "192.0.2.10",
                    "rx_bps": int(rx_mbps * 1_000_000),
                    "tx_bps": int(rx_mbps * 0.10 * 1_000_000),
                    "status": "synthetic experimental; subscriber identity/role contract pending",
                    "source": "sim_supplemental",
                }
            )
            for bh_index, backhaul in enumerate(site.get("backhauls", [])):
                loss_pct = max(0.0, rng.normal(0.12, 0.07))
                if event == "wireless_interference" and bh_index == 0:
                    loss_pct = min(35.0, max(8.0, rng.normal(15.0, 2.0)))
                rows.append(
                    {
                        "time": instant,
                        "site_id": site["id"],
                        "kind": "backhaul_quality",
                        "entity": backhaul["interface"],
                        "loss_pct": float(loss_pct),
                        "status": "synthetic experimental; interface role contract pending",
                        "source": "sim_supplemental",
                    }
                )
    return pd.DataFrame(rows)


def generate_subscribers(
    labels: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    seed: int = 42,
    site_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Generate continuous, core-shaped subscriber observations."""
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise ValueError("subscriber end must follow start")
    selected = [
        s
        for s in sites()["sites"]
        if (site_ids is not None and s["id"] in site_ids)
        or (site_ids is None and not s.get("runtime_only"))
    ]
    times = pd.date_range(start=start, end=end, freq="30s", inclusive="left", tz="UTC")
    rows = []
    for ix, site in enumerate(selected):
        rng = np.random.default_rng(seed + ix * 997)
        active = [label for label in labels if label["site_id"] == site["id"]]
        for stamp in times:
            instant = stamp.to_pydatetime()
            heavy = any(
                x["cause"] == "heavy_user" and x["start"] <= instant < x["end"] for x in active
            )
            rx = max(100_000, int((75 if heavy else rng.gamma(2, 900_000) / 1_000_000) * 1_000_000))
            rows.append(
                {
                    "time": instant,
                    "site_id": site["id"],
                    "ip": "192.0.2.10",
                    "rx_bps": rx,
                    "tx_bps": max(50_000, int(rx * 0.1)),
                    "source": "sim",
                }
            )
    return pd.DataFrame(rows, columns=list(SubscriberMetric.model_fields))


def site_from_fixture(site_id: str) -> Site:
    """Convert fixture topology to the shared core Site contract."""
    raw = next((s for s in sites()["sites"] if s["id"] == site_id), None)
    if raw is None:
        raise ValueError(f"unknown site: {site_id}")
    uplinks = [
        Uplink(
            iface=x["interface"],
            role=UplinkRole(x["role"]),
            capacity_mbps=x["capacity_mbps"],
            gateway=x.get("gateway"),
        )
        for x in raw["uplinks"]
    ]
    if raw.get("backup_uplink"):
        x = raw["backup_uplink"]
        uplinks.append(
            Uplink(
                iface=x["interface"],
                role=UplinkRole.BACKUP,
                capacity_mbps=x["capacity_mbps"],
                gateway=x.get("gateway"),
            )
        )
    uplinks.extend(
        Uplink(
            iface=x["interface"],
            role=UplinkRole.BACKHAUL,
            capacity_mbps=x["capacity_mbps"],
            gateway=x.get("gateway"),
        )
        for x in raw.get("backhauls", [])
    )
    role = {
        "gateway": TargetRole.GATEWAY,
        "upstream-hop": TargetRole.UPSTREAM_HOP,
        "regional-game": TargetRole.GAME_SERVER,
        "1.1.1.1": TargetRole.PUBLIC_DNS,
        "8.8.8.8": TargetRole.PUBLIC_DNS,
    }
    targets = []
    for target in raw["targets"]:
        if target.startswith("dns:"):
            targets.append(
                ProbeTarget(
                    key=target,
                    host=target.removeprefix("dns:"),
                    kind=ProbeKind.DNS,
                    role=TargetRole.PUBLIC_DNS,
                )
            )
        else:
            target_role = role.get(
                target,
                TargetRole.GATEWAY if target == "10.0.0.1" else TargetRole.PUBLIC_DNS,
            )
            targets.append(ProbeTarget(key=target, host=target, role=target_role))
    if not any(target.key == "dns:1.1.1.1" for target in targets):
        targets.append(
            ProbeTarget(
                key="dns:1.1.1.1",
                host="1.1.1.1",
                kind=ProbeKind.DNS,
                role=TargetRole.PUBLIC_DNS,
            )
        )
    return Site(
        id=raw["id"],
        name=raw["name"],
        uplinks=uplinks,
        targets=targets,
        subscribers=raw["subscribers"],
    )


def _label(
    site: dict[str, Any], cause: str, start: datetime, end: datetime, seed: int
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    affected: dict[str, Any] = {}
    template_id = TEMPLATES[cause]
    if cause == "uplink_congestion":
        uplink = site["uplinks"][0]
        params = {
            "uplink": uplink["interface"],
            "uplink_mbps": max(1, int(uplink["capacity_mbps"] * 0.9)),
            "game_ports": "3074,3478-3480,27015-27050",
        }
        affected = {"iface": uplink["interface"]}
    if cause == "uplink_down":
        primary = site["uplinks"][0]
        backup = site.get("backup_uplink")
        affected = {
            "iface": primary["interface"],
            "backup_iface": backup["interface"] if backup else None,
        }
        if primary.get("gateway") and backup and backup.get("gateway"):
            params = {
                "primary_gateway": primary["gateway"],
                "backup_gateway": backup["gateway"],
                "backup_distance": 2,
            }
        else:
            template_id = "none"
    if cause == "heavy_user":
        params = {
            "target": "192.0.2.10",
            "upload_mbps": 1,
            "download_mbps": 10,
        }
        affected = {"ip": "192.0.2.10"}
    if cause == "dns_slow":
        params = {"servers": ["1.1.1.1", "8.8.8.8"]}
        affected = {"target": "dns:1.1.1.1"}
    if cause == "wireless_interference" and site.get("backhauls"):
        affected = {"iface": site["backhauls"][0]["interface"]}
    return {
        "site_id": site["id"],
        "start": start,
        "end": end,
        "cause": cause,
        "template_id": template_id,
        "params": params,
        "affected": affected,
        "seed": seed,
        "split": "generated",
    }


def inject_frames(
    site_id: str,
    scenario_type: str,
    duration_min: int = 15,
    seed: int = 42,
    start: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Create scenario fixture rows. This is not the core API inject contract."""
    p, i, labels = generate(
        days=1,
        seed=seed,
        start=start,
        scenario_type=scenario_type,
        duration_min=duration_min,
        site_id=site_id,
    )
    return p, i, labels[0]


def inject(
    site_id: str,
    scenario_type: Cause,
    duration_min: int,
    seed: int | None = None,
    *,
    now: datetime | None = None,
    database: Any = None,
) -> ScenarioLabel:
    """Atomically inject core-validated sim observations for a bounded window."""
    if not 1 <= duration_min <= 22 * 60:
        raise ValueError("duration_min must be between 1 and 1320 (22 hours)")
    cause = Cause(scenario_type)
    now = _utc(now or datetime.now(UTC))
    end = now + timedelta(minutes=duration_min)
    actual_seed = int(seed if seed is not None else np.random.SeedSequence().generate_state(1)[0])
    fixture_site = next((site for site in sites()["sites"] if site["id"] == site_id), None)
    if fixture_site is None:
        raise ValueError(f"unknown site: {site_id}")
    if site_id == "sim-tower":
        if cause is Cause.GAME_ROUTE_ISSUE:
            raise ValueError("sim-tower has no configured game-server probe target")
        if cause is Cause.WIRELESS_INTERFERENCE and not fixture_site.get("backhauls"):
            raise ValueError("sim-tower has no configured wireless backhaul to interfere with")
        return _inject_runtime_tower(
            cause=cause,
            duration_min=duration_min,
            seed=actual_seed,
            now=now,
            database=database,
        )
    setting = None
    if database is None:
        setting = Settings()
        if setting.database_url is None:
            raise ModuleUnavailable("DATABASE_URL is required for simulator injection")
    scenario_raw = _label(fixture_site, cause.value, now, end, actual_seed)
    label = ScenarioLabel(
        site_id=site_id,
        scenario_type=cause,
        start_at=now,
        end_at=end,
        affected=scenario_raw["affected"],
        expected_cause=cause,
        expected_template=TemplateId(scenario_raw["template_id"]),
        expected_params=scenario_raw["params"],
        seed=actual_seed,
        source=Source.SIM,
    )
    fixture_start = now - timedelta(hours=2)
    p, i, labels = generate(
        days=1,
        start=fixture_start,
        scenario_type=cause.value,
        duration_min=duration_min,
        site_id=site_id,
        seed=actual_seed,
    )
    p = p[(p.time >= now) & (p.time < end)]
    i = i[(i.time >= now) & (i.time < end)]
    subscriber = generate_subscribers(
        labels, start=now, end=end, seed=actual_seed, site_ids=[site_id]
    )
    probes = [ProbeMetric.model_validate(row) for row in p.to_dict("records")]
    ifaces = [IfaceMetric.model_validate(row) for row in i.to_dict("records")]
    subscribers = [SubscriberMetric.model_validate(row) for row in subscriber.to_dict("records")]
    # Label is written through the same transaction as observations. The advisory
    # lock serializes concurrent injectors for this site before overlap checking.
    pool = database if database is not None else core_db.get_pool(setting)
    with pool.connection() as conn, conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (site_id,))
            cur.execute(
                "SELECT 1 FROM scenario_labels WHERE site_id=%s AND source='sim' "
                "AND start_at < %s AND COALESCE(end_at, 'infinity') > %s LIMIT 1",
                (site_id, end, now),
            )
            if cur.fetchone():
                raise ValueError("an injected scenario overlaps this site and time window")
        if core_db.fetch_site(conn, site_id) is None:
            core_db.upsert_site(conn, site_from_fixture(site_id))
        core_db.insert_probe_metrics(conn, probes)
        core_db.insert_iface_metrics(conn, ifaces)
        core_db.insert_subscriber_metrics(conn, subscribers)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scenario_labels (id, site_id, scenario_type, start_at, end_at, "
                "affected, expected_cause, expected_template, expected_params, seed, source) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    label.id,
                    label.site_id,
                    label.scenario_type.value,
                    label.start_at,
                    label.end_at,
                    Jsonb(label.affected),
                    label.expected_cause.value,
                    label.expected_template.value,
                    Jsonb(label.expected_params),
                    label.seed,
                    label.source.value,
                ),
            )
    return label


_RUNTIME_TARGETS = {
    "10.0.0.1": (ProbeKind.ICMP, 2.0),
    "1.1.1.1": (ProbeKind.ICMP, 18.0),
    "8.8.8.8": (ProbeKind.ICMP, 25.0),
    "dns:192.0.2.53": (ProbeKind.DNS, 22.0),
    "dns:1.1.1.1": (ProbeKind.DNS, 12.0),
}
_RUNTIME_SUBSCRIBERS = {
    "10.0.0.42": 4.0,
    "10.0.0.57": 3.0,
    "10.0.0.63": 2.5,
}
_RUNTIME_RECOVERY_MIN = 20
_RUNTIME_BACKFILL_MIN = 30
_RUNTIME_BATCH_SIZE = 1000


def _aligned_times(start: datetime, end: datetime, seconds: int):
    """Yield cadence timestamps aligned to UTC epoch boundaries."""
    epoch = int(start.timestamp())
    first = ((epoch + seconds - 1) // seconds) * seconds
    stamp = datetime.fromtimestamp(first, UTC)
    while stamp < end:
        if stamp >= start:
            yield stamp
        stamp += timedelta(seconds=seconds)


def _runtime_rows(
    start: datetime,
    end: datetime,
    cause: Cause | None,
    seed: int,
) -> tuple[list[ProbeMetric], list[IfaceMetric], list[SubscriberMetric]]:
    """Build actual core metrics for sim-tower, including its distinct DNS probes."""
    rng = np.random.default_rng(seed)
    probes: list[ProbeMetric] = []
    ifaces: list[IfaceMetric] = []
    subscribers: list[SubscriberMetric] = []
    for stamp in _aligned_times(start, end, 10):
        for target, (kind, baseline) in _RUNTIME_TARGETS.items():
            rtt: float | None = max(0.1, baseline * rng.uniform(0.9, 1.15))
            loss = 0.0
            if cause is Cause.DNS_SLOW and target == "dns:192.0.2.53":
                rtt, loss = float(rng.uniform(585, 715)), 20.0
            elif cause is Cause.UPLINK_DOWN and target in {"1.1.1.1", "8.8.8.8"}:
                rtt, loss = None, 100.0
            elif cause is Cause.HEAVY_USER and target in {"1.1.1.1", "8.8.8.8"}:
                rtt *= 5.5
            elif cause is Cause.UPLINK_CONGESTION and target in {"1.1.1.1", "8.8.8.8"}:
                rtt *= 3.5
            elif cause is Cause.UPSTREAM_DEGRADATION and target in {"1.1.1.1", "8.8.8.8"}:
                rtt *= 2.5
            elif cause is Cause.GAME_ROUTE_ISSUE and target == "8.8.8.8":
                rtt *= 4.5
            elif cause is Cause.WIRELESS_INTERFERENCE and target == "10.0.0.1":
                rtt *= 3.0
                loss = 12.0
            probes.append(
                ProbeMetric(
                    time=stamp,
                    site_id="sim-tower",
                    target=target,
                    kind=kind,
                    rtt_ms=rtt,
                    jitter_ms=None if rtt is None else max(0.1, rtt * 0.08),
                    loss_pct=loss,
                    source=Source.SIM,
                )
            )
    for stamp in _aligned_times(start, end, 30):
        rates = dict(_RUNTIME_SUBSCRIBERS)
        if cause is Cause.HEAVY_USER:
            rates["10.0.0.42"] = 140.0
        for ip, mbps in rates.items():
            rx = int(mbps * rng.uniform(0.9, 1.1) * 1_000_000)
            subscribers.append(
                SubscriberMetric(
                    time=stamp,
                    site_id="sim-tower",
                    ip=ip,
                    rx_bps=rx,
                    tx_bps=rx // 10,
                    source=Source.SIM,
                )
            )
        for iface, capacity, util in (
            (
                "ether1",
                180,
                0.0
                if cause is Cause.UPLINK_DOWN
                else 98.0
                if cause is Cause.UPLINK_CONGESTION
                else 92.0
                if cause is Cause.HEAVY_USER
                else 55.0,
            ),
            (
                "ether2",
                80,
                12.0
                if cause is Cause.UPLINK_DOWN
                else 0.5,
            ),
        ):
            actual = util * rng.uniform(0.97, 1.01)
            rx = int(capacity * 1_000_000 * max(0.0, actual) / 100)
            ifaces.append(
                IfaceMetric(
                    time=stamp,
                    site_id="sim-tower",
                    iface=iface,
                    rx_bps=rx,
                    tx_bps=rx // 8,
                    util_pct=max(0.0, actual),
                    drops=15 if cause is Cause.UPLINK_CONGESTION else 0,
                    errors=1 if cause is Cause.UPLINK_DOWN and iface == "ether1" else 0,
                    source=Source.SIM,
                )
            )
    return probes, ifaces, subscribers


def _existing_runtime_keys(conn: Any, table: str, start: datetime, end: datetime) -> set[tuple]:
    columns = {
        "probe_metrics": "time, target",
        "iface_metrics": "time, iface",
        "subscriber_metrics": "time, ip",
    }
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {columns[table]} FROM {table} WHERE site_id=%s AND source='sim' "
            "AND time >= %s AND time < %s",
            ("sim-tower", start, end),
        )
        return {tuple(row) for row in cur.fetchall()}


def _insert_bounded(helper: Any, conn: Any, rows: list[Any]) -> None:
    for offset in range(0, len(rows), _RUNTIME_BATCH_SIZE):
        helper(conn, rows[offset : offset + _RUNTIME_BATCH_SIZE])


def _insert_runtime_rows(conn: Any, start: datetime, end: datetime, cause: Cause | None, seed: int):
    probes, ifaces, subscribers = _runtime_rows(start, end, cause, seed)
    existing = {
        "probe": _existing_runtime_keys(conn, "probe_metrics", start, end),
        "iface": _existing_runtime_keys(conn, "iface_metrics", start, end),
        "subscriber": _existing_runtime_keys(conn, "subscriber_metrics", start, end),
    }
    probes = [r for r in probes if (r.time, r.target) not in existing["probe"]]
    ifaces = [r for r in ifaces if (r.time, r.iface) not in existing["iface"]]
    subscribers = [r for r in subscribers if (r.time, r.ip) not in existing["subscriber"]]
    _insert_bounded(core_db.insert_probe_metrics, conn, probes)
    _insert_bounded(core_db.insert_iface_metrics, conn, ifaces)
    _insert_bounded(core_db.insert_subscriber_metrics, conn, subscribers)


def _replace_prior_runtime_recovery(conn: Any, now: datetime) -> None:
    """Remove only future simulator rows within the preceding scenario's scripted recovery."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT end_at FROM scenario_labels WHERE site_id=%s AND source='sim' "
            "AND end_at <= %s AND end_at + interval '20 minutes' > %s "
            "ORDER BY end_at DESC LIMIT 1",
            ("sim-tower", now, now),
        )
        row = cur.fetchone()
    if row is None:
        return
    recovery_end = row[0] + timedelta(minutes=_RUNTIME_RECOVERY_MIN)
    for table in ("probe_metrics", "iface_metrics", "subscriber_metrics"):
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {table} WHERE site_id=%s AND source='sim' "
                "AND time >= %s AND time < %s",
                ("sim-tower", now, recovery_end),
            )


def _runtime_label(cause: Cause, duration_min: int, seed: int, now: datetime):
    end = now + timedelta(minutes=duration_min)
    fixture_site = next(x for x in sites()["sites"] if x["id"] == "sim-tower")
    scenario = _label(fixture_site, cause.value, now, end, seed)
    params = scenario["params"]
    affected = scenario["affected"]
    if cause is Cause.HEAVY_USER:
        params = {"target": "10.0.0.42", "upload_mbps": 5, "download_mbps": 10}
        affected = {"ip": "10.0.0.42"}
    elif cause is Cause.DNS_SLOW:
        params = {"servers": ["1.1.1.1", "8.8.8.8"]}
        affected = {"resolver": "192.0.2.53"}
    elif cause is Cause.UPLINK_DOWN:
        params = {
            "primary_gateway": "10.0.2.2",
            "backup_gateway": "192.0.2.1",
            "backup_distance": 2,
        }
        affected = {"iface": "ether1", "backup_iface": "ether2"}
    elif cause is Cause.UPLINK_CONGESTION:
        params = {
            "uplink": "ether1",
            "uplink_mbps": 162,
            "game_ports": "3074,3478-3480,27015-27050",
        }
        affected = {"iface": "ether1"}
    elif cause is Cause.GAME_ROUTE_ISSUE:
        affected = {"target": "8.8.8.8"}
    elif cause is Cause.WIRELESS_INTERFERENCE:
        affected = {"target": "10.0.0.1"}
    return ScenarioLabel(
        site_id="sim-tower",
        scenario_type=cause,
        start_at=now,
        end_at=end,
        affected=affected,
        expected_cause=cause,
        expected_template=TemplateId(scenario["template_id"]),
        expected_params=params,
        seed=seed,
        source=Source.SIM,
    )


def _inject_runtime_tower(
    *,
    cause: Cause,
    duration_min: int,
    seed: int,
    now: datetime,
    database: Any,
) -> ScenarioLabel:
    """Persist normal backfill, a runtime incident, and scripted recovery atomically."""
    now = now.replace(second=(now.second // 10) * 10, microsecond=0)
    end = now + timedelta(minutes=duration_min)
    label = _runtime_label(cause, duration_min, seed, now)
    setting = None
    if database is None:
        setting = Settings()
        if setting.database_url is None:
            raise ModuleUnavailable("DATABASE_URL is required for simulator injection")
    pool = database if database is not None else core_db.get_pool(setting)
    with pool.connection() as conn, conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("sim-tower",))
            cur.execute(
                "SELECT 1 FROM scenario_labels WHERE site_id=%s AND source='sim' "
                "AND start_at < %s AND COALESCE(end_at, 'infinity') > %s LIMIT 1",
                ("sim-tower", end, now),
            )
            if cur.fetchone():
                raise ValueError("an injected scenario overlaps this site and time window")
        if core_db.fetch_site(conn, "sim-tower") is None:
            core_db.upsert_site(conn, site_from_fixture("sim-tower"))
        _replace_prior_runtime_recovery(conn, now)
        backfill_start = now - timedelta(minutes=_RUNTIME_BACKFILL_MIN)
        _insert_runtime_rows(conn, backfill_start, now, None, seed)
        _insert_runtime_rows(conn, now, end, cause, seed)
        recovery_end = end + timedelta(minutes=_RUNTIME_RECOVERY_MIN)
        _insert_runtime_rows(conn, end, recovery_end, None, seed)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scenario_labels (id, site_id, scenario_type, start_at, end_at, "
                "affected, expected_cause, expected_template, expected_params, seed, source) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    label.id,
                    label.site_id,
                    label.scenario_type.value,
                    label.start_at,
                    label.end_at,
                    Jsonb(label.affected),
                    label.expected_cause.value,
                    label.expected_template.value,
                    Jsonb(label.expected_params),
                    label.seed,
                    label.source.value,
                ),
            )
    return label
