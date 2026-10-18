from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import yaml

if TYPE_CHECKING:
    from netcortex_core import Cause, ScenarioLabel


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
    selected = [s for s in layout if site_id is None or s["id"] == site_id]
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
                        "rtt_ms": rtt,
                        "jitter_ms": np.maximum(0.1, jitter),
                        "loss_pct": loss,
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
    times = pd.date_range(start=start, end=end, freq="30s", inclusive="both", tz="UTC")
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


def _label(
    site: dict[str, Any], cause: str, start: datetime, end: datetime, seed: int
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cause == "uplink_congestion":
        params = {"interface": site["uplinks"][0]["interface"], "priority": "high"}
    if cause == "uplink_down":
        params = (
            {
                "primary": site["uplinks"][0]["interface"],
                "backup": site["backup_uplink"]["interface"],
            }
            if site.get("backup_uplink")
            else {
                "primary": site["uplinks"][0]["interface"],
                "backup": None,
                "actionable": False,
            }
        )
    if cause == "heavy_user":
        params = {
            "limit_mbps": 10,
            "evidence_status": "synthetic subscriber row is supplemental; "
            "core subscriber contract pending",
        }
    if cause == "dns_slow":
        params = {
            "template": "dns_servers",
            "evidence_status": "experimental resolution rows are supplemental",
        }
    if cause == "wireless_interference":
        params = {
            "interface": site["backhauls"][0]["interface"],
            "evidence_status": "simulated interface counters; role contract pending",
        }
    return {
        "site_id": site["id"],
        "start": start,
        "end": end,
        "cause": cause,
        "template_id": TEMPLATES[cause],
        "params": params,
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
    site_id: str, scenario_type: Cause, duration_min: int, seed: int | None = None
) -> ScenarioLabel:
    """Core-facing contract entry point; unavailable until the real core arrives."""
    try:
        import importlib

        core = importlib.import_module("netcortex_core")
        for symbol in ("Cause", "ScenarioLabel"):
            getattr(core, symbol)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "Core injection unavailable: netcortex_core and its approved "
            "ScenarioLabel contract are not present"
        ) from exc
    raise RuntimeError(
        "Core injection adapter is unbound: confirm core injection lifecycle, "
        "Cause values, and ScenarioLabel construction before enabling"
    )
