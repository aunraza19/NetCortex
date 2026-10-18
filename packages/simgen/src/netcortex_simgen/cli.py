from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .ripe import fetch as fetch_ripe
from .simulator import CAUSES, ROOT, generate, generate_supplemental, inject_frames, sites

PING_TARGET_ROLES = {
    "gateway",
    "upstream_hop",
    "public_dns_reachability_proxy",
    "game_server",
}


def _read_target_role_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    mapping = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or any(
        not isinstance(target, str) or not isinstance(role, str) for target, role in mapping.items()
    ):
        raise ValueError("target role map must contain exact target-string keys and role names")
    unknown_roles = set(mapping.values()) - PING_TARGET_ROLES
    if unknown_roles:
        raise ValueError(
            "RIPE ping roles must describe ping observations; unsupported roles: "
            + ", ".join(sorted(unknown_roles))
        )
    return mapping


def _build_calibration(
    observations: pd.DataFrame,
    target_role_map: dict[str, str] | None = None,
    *,
    allow_role_proxy: bool = False,
) -> dict[str, Any]:
    """Summarize observed samples by Pakistan hour and exact target."""
    if "time" not in observations or "rtt_ms" not in observations:
        raise ValueError("calibration input must contain time and rtt_ms columns")
    df = observations.copy()
    df["time"] = pd.to_datetime(df.time, utc=True)
    df["rtt_ms"] = pd.to_numeric(df.rtt_ms, errors="coerce")
    for column in ("jitter_ms", "loss_pct"):
        if column not in df:
            df[column] = pd.NA
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["hour_pk"] = df.time.dt.tz_convert("Asia/Karachi").dt.hour
    if "target" not in df:
        df["target"] = "unknown"
    df["target"] = df.target.astype(str)
    roles = target_role_map or {}
    if "target_role" not in df:
        df["target_role"] = "unmapped_ripe_public_ping"
    df["target_role"] = [
        roles.get(target, role) for target, role in zip(df.target, df.target_role, strict=True)
    ]

    hourly = (
        df.groupby("hour_pk")
        .agg(
            rtt_ms=("rtt_ms", "median"),
            jitter_ms=("jitter_ms", "median"),
            loss_pct=("loss_pct", "median"),
            sample_count=("rtt_ms", "count"),
        )
        .reset_index()
    )
    target_hourly_stats: dict[str, dict[str, dict[str, float | int]]] = {}
    target_hourly: dict[str, dict[str, float]] = {}
    for (target, hour), group in df.groupby(["target", "hour_pk"], dropna=True):
        stats: dict[str, float | int] = {"sample_count": int(group.rtt_ms.count())}
        for column in ("rtt_ms", "jitter_ms", "loss_pct"):
            value = group[column].median()
            if pd.notna(value):
                stats[column] = float(value)
        target_hourly_stats.setdefault(str(target), {})[str(int(hour))] = stats
        if "rtt_ms" in stats:
            target_hourly.setdefault(str(target), {})[str(int(hour))] = stats["rtt_ms"]

    target_medians = df.groupby("target").rtt_ms.median().dropna().astype(float).to_dict()
    target_stats: dict[str, dict[str, float | int]] = {}
    for target, group in df.groupby("target"):
        stats: dict[str, float | int] = {"sample_count": int(group.rtt_ms.count())}
        for column in ("rtt_ms", "jitter_ms", "loss_pct"):
            value = group[column].median()
            if pd.notna(value):
                stats[column] = float(value)
        target_stats[str(target)] = stats
    target_roles: dict[str, str] = {}
    for target, group in df.groupby("target"):
        if target in roles:
            target_roles[str(target)] = roles[target]
        else:
            observed = set(group.target_role.dropna().astype(str))
            if len(observed) == 1:
                target_roles[str(target)] = next(iter(observed))
    role_medians: dict[str, dict[str, float | int]] = {}
    role_hourly_stats: dict[str, dict[str, dict[str, float | int]]] = {}
    mapped = df[df.target.isin(roles)].copy()
    if not mapped.empty:
        mapped["target_role"] = mapped.target.map(roles)
    for role, group in mapped.groupby("target_role"):
        role_stats: dict[str, float | int] = {"sample_count": int(group.rtt_ms.count())}
        for column in ("rtt_ms", "jitter_ms", "loss_pct"):
            value = group[column].median()
            if pd.notna(value):
                role_stats[column] = float(value)
        role_medians[str(role)] = role_stats
        for hour, hour_group in group.groupby("hour_pk"):
            stats = {"sample_count": int(hour_group.rtt_ms.count())}
            for column in ("rtt_ms", "jitter_ms", "loss_pct"):
                value = hour_group[column].median()
                if pd.notna(value):
                    stats[column] = float(value)
            role_hourly_stats.setdefault(str(role), {})[str(int(hour))] = stats
    observed_targets = set(df.target.astype(str))
    proxy_sources = sorted(
        target
        for target, role in roles.items()
        if target in observed_targets and role == "public_dns_reachability_proxy"
    )
    proxy_enabled = allow_role_proxy and bool(proxy_sources)
    role_proxy = {
        "enabled": proxy_enabled,
        "role": "public_dns_reachability_proxy",
        "source_targets": proxy_sources,
        "configured_targets": ["1.1.1.1", "8.8.8.8"],
        "opt_in_required": ["exact target-role map", "--allow-role-proxy"],
        "uncertainty": (
            "These are public root-DNS-server ping paths. Their RTT, jitter, and loss are "
            "reachability proxies, not DNS lookup timing or proof of route equivalence to "
            "1.1.1.1 or 8.8.8.8."
        ),
        "status": (
            "enabled by explicit mapping and CLI flag"
            if proxy_enabled
            else "disabled; requires an explicit mapping and --allow-role-proxy"
        ),
    }
    return {
        "provenance": sorted(set(observations.source.astype(str)))
        if "source" in observations
        else ["unknown"],
        "experimental_status": (
            "Hourly and target statistics are medians of observed samples only. "
            "Target/hour RTTs apply only when configured target names match. "
            "Role proxies require an explicit map and opt-in flag and are restricted to "
            "configured public DNS reachability targets. Ping reachability is not DNS "
            "resolution timing."
        ),
        "target_medians_ms": target_medians,
        "target_stats": target_stats,
        "target_hourly_ms": target_hourly,
        "target_hourly_stats": target_hourly_stats,
        "role_medians": role_medians,
        "role_hourly_stats": role_hourly_stats,
        "role_proxy": role_proxy,
        "target_roles": target_roles,
        "hourly": hourly.to_dict("records"),
    }


def _write_calibration_report(
    observations: pd.DataFrame, calibration: dict[str, Any], gaps: list[dict[str, Any]]
) -> str:
    """Render measured coverage and explicit simulator-baseline mapping status."""
    from .simulator import TARGETS

    display = observations.copy()
    for column in ("target", "rtt_ms", "loss_pct"):
        if column not in display:
            display[column] = pd.NA
    display["target"] = display.target.fillna("unknown").astype(str)
    times = pd.to_datetime(display.time, utc=True, errors="coerce").dropna()
    targets = display.target.astype(str)
    measurement_ids = (
        sorted(observations.measurement_id.dropna().astype(str).unique())
        if "measurement_id" in observations
        else []
    )
    probes = (
        sorted(observations.probe_id.dropna().astype(str).unique())
        if "probe_id" in observations
        else []
    )
    asns = (
        sorted(observations.probe_asn.dropna().astype(str).unique())
        if "probe_asn" in observations
        else []
    )
    exact_targets = set(targets.unique()) & set(TARGETS)
    proxy = calibration.get("role_proxy", {})
    proxy_role_stats = calibration.get("role_medians", {}).get("public_dns_reachability_proxy", {})
    span = f"{times.min().isoformat()} through {times.max().isoformat()}" if len(times) else "none"
    rows = [
        "# RIPE calibration report",
        "",
        "This report summarizes downloaded public ping observations. The targets are "
        "DNS-server "
        "reachability probes; RTT is not DNS lookup latency.",
        "",
        "## Coverage",
        "",
        f"- Observations: {len(observations):,}",
        f"- UTC coverage: {span}",
        f"- Distinct UTC dates: {times.dt.floor('D').nunique() if len(times) else 0}",
        f"- Measurement IDs: {', '.join(measurement_ids) if measurement_ids else 'none'}",
        f"- Probe IDs: {', '.join(probes) if probes else 'none'}",
        f"- Probe ASNs: {', '.join(asns) if asns else 'none'}",
        "",
        "| Public ping target | Rows | Median RTT (ms) | Median loss (%) | "
        "Pakistan hours observed |",
        "|---|---:|---:|---:|---:|",
    ]
    for target, group in display.groupby("target", dropna=False):
        rtt = pd.to_numeric(group.rtt_ms, errors="coerce")
        loss = pd.to_numeric(group.loss_pct, errors="coerce")
        local_hours = pd.to_datetime(group.time, utc=True).dt.tz_convert("Asia/Karachi").dt.hour
        rows.append(
            f"| {target} | {len(group):,} | {rtt.median():.2f} | "
            f"{loss.median():.2f} | {local_hours.nunique()}/24 |"
        )
    rows.extend(
        [
            "",
            "| Measurement ID | Rows | UTC dates covered | Targets |",
            "|---:|---:|---:|---|",
        ]
    )
    if "measurement_id" in observations:
        for measurement_id, group in display.groupby("measurement_id", dropna=False):
            dates = pd.to_datetime(group.time, utc=True).dt.floor("D").nunique()
            target_names = ", ".join(sorted(group.target.astype(str).unique()))
            rows.append(f"| {measurement_id} | {len(group):,} | {dates} | {target_names} |")
    rows.extend(
        [
            "",
            "## Calibration use and gaps",
            "",
            f"- Exact configured simulator target matches: {len(exact_targets)}/{len(TARGETS)} "
            f"({', '.join(sorted(exact_targets)) if exact_targets else 'none'}).",
            "- Public DNS role-proxy transfer: "
            f"{'enabled' if proxy.get('enabled') else 'disabled'}.",
            f"- Explicit source targets: {', '.join(proxy.get('source_targets', [])) or 'none'}.",
            "- Proxy destination targets: "
            f"{', '.join(proxy.get('configured_targets', [])) or 'none'}.",
            "- Exact target calibration takes precedence. Role proxy can fill only "
            "unmatched configured public DNS targets (`1.1.1.1`, `8.8.8.8`); it never "
            "changes gateway, upstream-hop, regional-game, or DNS resolution timing.",
            "- Role medians (only when explicitly mapped): "
            f"RTT {proxy_role_stats.get('rtt_ms', 'n/a')} ms, "
            f"jitter {proxy_role_stats.get('jitter_ms', 'n/a')} ms, "
            f"loss {proxy_role_stats.get('loss_pct', 'n/a')}%, "
            f"n={proxy_role_stats.get('sample_count', 0):,}.",
            f"- Transfer uncertainty: {proxy.get('uncertainty', 'No role transfer enabled.')}",
            "- The requested window covers seven UTC days. Daily failures remain in "
            "`data/ripe-baseline-summary.json`; they are not imputed.",
            f"- Failed daily requests recorded in the fetch summary: {len(gaps)}.",
            "- Proxy source samples are restricted to exact observed target strings in the "
            "supplied map; provider role labels alone never authorize transfer.",
            "",
            "Pakistan-hour target and role medians are stored in ignored `data/calibration.json`. "
            "Role transfer is off by default and requires both an exact-target role map and "
            "`--allow-role-proxy`.",
            "",
        ]
    )
    if gaps:
        rows.extend(["", "Failed daily requests:"])
        for gap in gaps:
            stamp = pd.to_datetime(gap.get("start"), unit="s", utc=True).date()
            rows.append(
                f"- {stamp}, measurement {gap.get('measurement')}: "
                f"{gap.get('error', 'request failed')}"
            )
    role_hours = calibration.get("role_hourly_stats", {}).get("public_dns_reachability_proxy", {})
    if role_hours:
        rows.extend(
            [
                "",
                "## Explicit role-proxy statistics by Pakistan hour",
                "",
                "| Hour PK | Median RTT (ms) | Median jitter (ms) | "
                "Median loss (%) | RTT samples |",
                "|---:|---:|---:|---:|---:|",
            ]
        )
        for hour, stats in sorted(role_hours.items(), key=lambda item: int(item[0])):
            rows.append(
                f"| {hour} | {stats.get('rtt_ms', 'n/a')} | "
                f"{stats.get('jitter_ms', 'n/a')} | {stats.get('loss_pct', 'n/a')} | "
                f"{stats.get('sample_count', 0):,} |"
            )
    return "\n".join(rows)


def _write(
    p: pd.DataFrame,
    i: pd.DataFrame,
    labels: list[dict[str, Any]],
    directory: Path,
    supplemental: pd.DataFrame | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    p.to_parquet(directory / "probe_metrics.parquet", index=False)
    i.to_parquet(directory / "iface_metrics.parquet", index=False)
    pd.DataFrame(labels).to_json(
        directory / "scenario_labels.json",
        orient="records",
        date_format="iso",
        indent=2,
    )
    (directory / "generation_metadata.json").write_text(
        json.dumps(
            {
                "source": "sim",
                "calibration": p.attrs.get("calibration", {}),
            },
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    if supplemental is not None:
        supplemental.to_parquet(directory / "supplemental_experimental.parquet", index=False)


def _load_database(p: pd.DataFrame, i: pd.DataFrame, source: str) -> None:
    if not os.getenv("NETCORTEX_DB_KEYS_CONFIRMED") == "1":
        raise RuntimeError(
            "Database load disabled until Aun confirms repeat-safe database keys; "
            "set NETCORTEX_DB_KEYS_CONFIRMED=1 only after the contract is published"
        )
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")
    import psycopg

    with psycopg.connect(dsn) as conn, conn.transaction():
        # The approved conflict keys are intentionally a gate. Never guess table keys.
        raise RuntimeError(
            "Core table key/upsert contract is not yet confirmed; no rows were written"
        )


def _read_source(
    source: str, last: str, *, include_injections: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = ROOT / "data/generated"
    if source == "sim":
        p = pd.read_parquet(base / "probe_metrics.parquet")
        i = pd.read_parquet(base / "iface_metrics.parquet")
    elif source == "ripe":
        path = ROOT / "data/raw/ripe/results.parquet"
        if not path.exists():
            raise FileNotFoundError("RIPE results are missing; run `simgen ripe` first")
        p = pd.read_parquet(path)
        i = pd.DataFrame(
            columns=[
                "time",
                "site_id",
                "iface",
                "rx_bps",
                "tx_bps",
                "util_pct",
                "drops",
                "errors",
                "source",
            ]
        )
    else:
        raise ValueError(f"unsupported source: {source}")
    if include_injections and source == "sim":
        folder = base / "injections"
        registry = folder / "active_scenarios.json"
        if registry.exists():
            for item in json.loads(registry.read_text(encoding="utf-8")):
                key = item["id"]
                pp, ii = (
                    folder / f"{key}-probe.parquet",
                    folder / f"{key}-iface.parquet",
                )
                if pp.exists():
                    p = pd.concat([p, pd.read_parquet(pp)], ignore_index=True)
                if ii.exists():
                    i = pd.concat([i, pd.read_parquet(ii)], ignore_index=True)
    amount = last.strip().lower()
    if amount.endswith("d"):
        delta = pd.Timedelta(days=float(amount[:-1]))
    elif amount.endswith("h"):
        delta = pd.Timedelta(hours=float(amount[:-1]))
    else:
        raise ValueError("--last must be a duration such as 2d or 12h")
    if delta <= pd.Timedelta(0):
        raise ValueError("--last must be positive")
    if len(p) and "time" in p:
        edge = pd.to_datetime(p.time, utc=True).max() - delta
        p = p[pd.to_datetime(p.time, utc=True) >= edge]
        if len(i) and "time" in i:
            i = i[pd.to_datetime(i.time, utc=True) >= edge]
    return p, i


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simgen", description="NetCortex deterministic telemetry fixtures"
    )
    subs = parser.add_subparsers(dest="command", required=True)
    ripe = subs.add_parser("ripe")
    ripe.add_argument("--days", type=int, default=14)
    ripe.add_argument("--max-probes", type=int, default=5)
    ripe.add_argument("--max-measurements", type=int, default=5)
    ripe.add_argument("--mock", action="store_true")
    cal = subs.add_parser("calibrate")
    cal.add_argument("--mock", action="store_true")
    cal.add_argument(
        "--target-role-map",
        type=Path,
        help="JSON mapping exact observed ping targets to operator-approved ping roles",
    )
    cal.add_argument(
        "--allow-role-proxy",
        action="store_true",
        help=(
            "opt in to using explicitly mapped public DNS reachability-role statistics "
            "for configured public DNS targets"
        ),
    )
    gen = subs.add_parser("generate")
    gen.add_argument("--days", type=int, default=7)
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--normal-only", action="store_true")
    gen.add_argument("--mock", action="store_true")
    load = subs.add_parser("load")
    load.add_argument("--source", default="sim", choices=["sim", "ripe"])
    load.add_argument("--last", default="2d")
    load.add_argument("--mock", action="store_true")
    replay = subs.add_parser("replay")
    replay.add_argument("--speed", type=float, default=1)
    replay.add_argument("--mock", action="store_true")
    replay.add_argument("--limit", type=int)
    inj = subs.add_parser("inject")
    inj.add_argument("--site", required=True)
    inj.add_argument("--type", required=True, choices=CAUSES)
    inj.add_argument("--duration", type=int, default=15)
    inj.add_argument("--seed", type=int, default=42)
    inj.add_argument("--mock", action="store_true")
    ev = subs.add_parser("eval-cases")
    ev.add_argument(
        "--n",
        type=int,
        default=80,
        help="held-out test cases per split; multiple of eight, including normal",
    )
    ev.add_argument("--seed", type=int, default=1000)
    ev.add_argument("--mock", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mock = getattr(args, "mock", False)
    if args.command == "ripe":
        if mock:
            raise SystemExit(
                "RIPE fixture fetch has no bundled real-observation fixture; "
                "use an explicit recorded fixture"
            )
        frame = fetch_ripe(
            args.days,
            ROOT / "data/raw/ripe/results.parquet",
            max_probes=args.max_probes,
            max_measurements=args.max_measurements,
        )
        if len(frame):
            lo = pd.to_datetime(frame.time, utc=True).min().isoformat()
            hi = pd.to_datetime(frame.time, utc=True).max().isoformat()
            probes = frame.probe_id.nunique() if "probe_id" in frame else 0
            asns = frame.probe_asn.nunique() if "probe_asn" in frame else 0
            print(
                f"Fetched {len(frame)} RIPE rows from {probes} probes/{asns} ASNs; "
                f"coverage {lo} to {hi}; source provenance retained"
            )
        else:
            print("RIPE discovery completed but returned no matching result rows")
    elif args.command == "calibrate":
        if mock:
            raise SystemExit(
                "`calibrate --mock` is unavailable: no mock observations are bundled; "
                "calibration will never substitute invented data"
            )
        paths = [
            ROOT / "data/raw/ripe/results.parquet",
            ROOT / "data/raw/live/collector.parquet",
        ]
        frames = [pd.read_parquet(path) for path in paths if path.exists()]
        if not frames:
            raise SystemExit(
                "No RIPE/live rows available. Calibration not written; "
                "defaults remain simulator assumptions."
            )
        df = pd.concat(frames, ignore_index=True)
        role_map = _read_target_role_map(args.target_role_map)
        if args.allow_role_proxy and not role_map:
            raise SystemExit(
                "--allow-role-proxy requires --target-role-map with explicit role entries"
            )
        if args.allow_role_proxy and "public_dns_reachability_proxy" not in role_map.values():
            raise SystemExit(
                "--allow-role-proxy requires at least one exact target mapped to "
                "public_dns_reachability_proxy"
            )
        calibration = _build_calibration(
            df,
            role_map,
            allow_role_proxy=args.allow_role_proxy,
        )
        calibration["observation_count"] = len(df)
        calibration["input_files"] = [
            str(path.relative_to(ROOT)) for path in paths if path.exists()
        ]
        times = pd.to_datetime(df.time, utc=True, errors="coerce").dropna()
        calibration["time_range_utc"] = (
            {"start": times.min().isoformat(), "end": times.max().isoformat()}
            if len(times)
            else None
        )
        out = ROOT / "data/calibration.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(calibration, indent=2), encoding="utf-8", newline="\n")
        summary_path = ROOT / "data/ripe-baseline-summary.json"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        )
        gaps = summary.get("failures", []) if isinstance(summary, dict) else []
        report = _write_calibration_report(df, calibration, gaps)
        (ROOT / "data/calibration-report.md").write_text(report, encoding="utf-8", newline="\n")
        configured_targets = {target for site in sites()["sites"] for target in site["targets"]}
        matched_targets = (
            set(df.target.astype(str)) & configured_targets if "target" in df else set()
        )
        print(
            f"Calibrated from {len(df):,} observed rows; exact configured target matches: "
            f"{len(matched_targets)}. "
            "See data/calibration-report.md for coverage and gaps."
        )
    elif args.command == "generate":
        p, i, labels = generate(args.days, args.seed, normal_only=args.normal_only)
        extra = generate_supplemental(
            labels,
            start=pd.to_datetime(p.time, utc=True).min().to_pydatetime(),
            end=pd.to_datetime(p.time, utc=True).max().to_pydatetime(),
            seed=args.seed,
            site_ids=[s["id"] for s in sites()["sites"]],
        )
        _write(p, i, labels, ROOT / "data/generated", extra)
        print(f"Wrote {len(p)} probe and {len(i)} interface rows")
    elif args.command == "inject":
        p, i, label = inject_frames(args.site, args.type, args.duration, args.seed)
        p = p[(p.time >= label["start"]) & (p.time < label["end"])].copy()
        i = i[(i.time >= label["start"]) & (i.time < label["end"])].copy()
        folder = ROOT / "data/generated/injections"
        folder.mkdir(parents=True, exist_ok=True)
        key = f"{args.site}-{args.type}-{args.seed}"
        p.to_parquet(folder / f"{key}-probe.parquet", index=False)
        i.to_parquet(folder / f"{key}-iface.parquet", index=False)
        generate_supplemental(
            [label],
            start=p.time.min().to_pydatetime(),
            end=p.time.max().to_pydatetime(),
            seed=args.seed,
            site_ids=[args.site],
        ).to_parquet(folder / f"{key}-supplemental.parquet", index=False)
        labels_path = folder / "active_scenarios.json"
        labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else []
        labels = [x for x in labels if x.get("id") != key]
        labels.append(
            {
                "id": key,
                "calibration": p.attrs.get("calibration", {}),
                **label,
                "start": label["start"].isoformat(),
                "end": label["end"].isoformat(),
            }
        )
        labels_path.write_text(json.dumps(labels, indent=2), encoding="utf-8")
        print(
            f"Fixture persisted as {key}; core injection/persistence unavailable "
            "until its lifecycle contract is published"
        )
    elif args.command == "load":
        p, i = _read_source(args.source, args.last)
        if mock:
            print(
                f"Mock load validated {len(p)} {args.source} probe rows and "
                f"{len(i)} interface rows; no database writes"
            )
        else:
            _load_database(p, i, args.source)
    elif args.command == "replay":
        if args.speed <= 0:
            raise SystemExit("--speed must be > 0")
        p, i = _read_source("sim", "365d", include_injections=True)
        p = p.sort_values("time")
        i = i.sort_values("time")
        # Speed 1 uses wall-clock time; larger values advance a virtual clock.
        if args.limit:
            p = p.head(args.limit)
            i = i[i.time <= p.time.max()]
        prev = None
        for _, row in p.iterrows():
            stamp = pd.Timestamp(row.time).to_pydatetime()
            if prev is not None and not mock and args.speed == 1:
                time.sleep(min(30, max(0, (stamp - prev).total_seconds())))
            prev = stamp
        if not mock:
            _load_database(p, i, "sim")
        active = ROOT / "data/generated/injections/active_scenarios.json"
        active_count = len(json.loads(active.read_text(encoding="utf-8"))) if active.exists() else 0
        print(
            f"Replay consumed {len(p)} probes and {len(i)} interfaces in time order; "
            f"active injections={active_count}, virtual speed={args.speed}"
        )
    elif args.command == "eval-cases":
        make_eval_cases(args.n, args.seed, ROOT / "eval/cases")
    return 0


def make_eval_cases(n: int, seed: int, out: Path) -> None:
    if n < 8 or n % 8:
        raise ValueError(
            "--n must be a positive multiple of eight so all seven causes and normal are balanced"
        )
    out.mkdir(parents=True, exist_ok=True)
    base_causes = ["normal", *CAUSES]
    for split_index, split in enumerate(("train", "validation", "test")):
        split_seed = seed + split_index * 1_000_000
        rng = np.random.default_rng(split_seed)
        case_types = base_causes * (n // len(base_causes))
        rng.shuffle(case_types)
        sites = ["north-tower", "market-cafe", "east-relay"]
        split_start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=split_index * (n * 2 + 60))
        for idx, cause in enumerate(case_types):
            case_seed = split_seed + int(rng.integers(1, 900_000))
            site = sites[int(rng.integers(0, len(sites)))]
            start = split_start + timedelta(days=idx * 2)
            p, i, labels = generate(
                days=1,
                hours=3,
                seed=case_seed,
                start=start,
                scenario_type=None if cause == "normal" else cause,
                normal_only=cause == "normal",
                site_id=site,
            )
            label = (
                labels[0]
                if labels
                else {
                    "site_id": site,
                    "start": None,
                    "end": None,
                    "cause": "normal",
                    "template_id": "none",
                    "params": {},
                }
            )
            as_of = (
                (label["end"] - timedelta(seconds=10))
                if label["end"]
                else (start + timedelta(hours=3) - timedelta(seconds=10))
            )
            window_start = as_of - timedelta(minutes=30)
            p = p[p.time <= as_of].copy()
            i = i[i.time <= as_of].copy()
            folder = out / split
            folder.mkdir(exist_ok=True)
            caseid = f"{split}-case-{idx:03d}"
            p.to_parquet(folder / f"{caseid}-probe.parquet", index=False)
            i.to_parquet(folder / f"{caseid}-iface.parquet", index=False)
            supplemental = generate_supplemental(
                labels,
                start=start,
                end=as_of,
                seed=case_seed,
                site_ids=[site],
            )
            supplemental.to_parquet(folder / f"{caseid}-supplemental.parquet", index=False)
            record = {
                "case_id": caseid,
                "split": split,
                "seed": case_seed,
                "site_id": site,
                "case_start": start.isoformat(),
                "event_start": label["start"].isoformat() if label["start"] else None,
                "event_end": label["end"].isoformat() if label["end"] else None,
                "as_of": as_of.isoformat(),
                "history_window": {
                    "start": start.isoformat(),
                    "end_exclusive": window_start.isoformat(),
                },
                "detection_window": {
                    "start": window_start.isoformat(),
                    "end_inclusive": as_of.isoformat(),
                },
                "expected": {
                    "cause": label["cause"],
                    "template_id": label["template_id"],
                    "params": label["params"],
                },
                "calibration": p.attrs.get("calibration", {}),
                "observations": {
                    "probe": f"{caseid}-probe.parquet",
                    "iface": f"{caseid}-iface.parquet",
                    "supplemental": f"{caseid}-supplemental.parquet",
                },
            }
            (folder / f"{caseid}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"Wrote {n} cases per split (train, validation, held-out test) to {out}")


if __name__ == "__main__":
    raise SystemExit(main())
