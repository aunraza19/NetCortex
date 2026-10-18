from __future__ import annotations

import hashlib
import json
import time
import warnings
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

API = "https://atlas.ripe.net/api/v2"
MAX_RAW_RESULT_ROWS_PER_MEASUREMENT = 50_000
MAX_RAW_RESULT_ROWS_PER_DAY = 10_000
MAX_SELECTED_ROWS_PER_MEASUREMENT = 50_000
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
REQUEST_PAUSE_SECONDS = 0.25


def parse_result(item: dict[str, Any], *, site_id: str = "ripe-pk") -> dict[str, Any] | None:
    """Parse one RIPE ping result without treating missing RTTs as successful."""
    timestamp = item.get("timestamp")
    if not isinstance(timestamp, (int, float)):
        return None
    raw = item.get("avg")
    sent = item.get("sent")
    rtts = item.get("result", item.get("rtts"))
    if isinstance(rtts, list):
        vals = [
            float(v["rtt"])
            for v in rtts
            if isinstance(v, dict) and isinstance(v.get("rtt"), (int, float)) and v["rtt"] >= 0
        ]
        received = len(vals)
        sent = sent if isinstance(sent, (int, float)) and sent > 0 else len(rtts)
        avg = sum(vals) / received if received else None
        jitter = float(pd.Series(vals).std(ddof=0)) if received else None
    else:
        received = item.get("rcvd")
        avg = float(raw) if isinstance(raw, (int, float)) and raw >= 0 else None
        jitter = None
        if not isinstance(received, (int, float)) and isinstance(sent, (int, float)):
            received = 1 if avg is not None else 0
    if not isinstance(received, (int, float)) or not isinstance(sent, (int, float)) or sent <= 0:
        return None
    return {
        "time": pd.to_datetime(timestamp, unit="s", utc=True),
        "site_id": site_id,
        "target": str(item.get("dst_addr", "unknown")),
        "rtt_ms": avg,
        "jitter_ms": jitter,
        "loss_pct": max(0.0, min(100.0, (sent - received) / sent * 100)),
        "source": "ripe",
        "measurement_id": item.get("msm_id"),
        "probe_id": item.get("prb_id"),
        "probe_asn": item.get("probe_asn"),
        "measurement_target": item.get("measurement_target"),
        "target_role": item.get("target_role", "unmapped_ripe_public_ping"),
    }


def _diverse_probes(probes: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Choose a bounded set of active probes spanning ASNs where possible."""
    selected: list[dict[str, Any]] = []
    seen_asns = set()
    for probe in probes:
        asn = probe.get("asn_v4") or probe.get("asn_v6")
        if asn not in seen_asns:
            selected.append(probe)
            seen_asns.add(asn)
        if len(selected) >= limit:
            return selected
    selected_ids = {probe.get("id") for probe in selected}
    for probe in probes:
        if probe.get("id") not in selected_ids:
            selected.append(probe)
        if len(selected) >= limit:
            break
    return selected


def _pages(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
    page_limit: int = 20,
    *,
    deadline: float | None = None,
    row_limit: int = MAX_RAW_RESULT_ROWS_PER_MEASUREMENT,
):
    row_count = 0
    for _ in range(page_limit):
        timeout = 15.0
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("RIPE fetch deadline elapsed")
            timeout = min(timeout, remaining)
        request_timeout = httpx.Timeout(timeout, connect=min(5.0, timeout))
        try:
            response = client.get(url, params=params, timeout=request_timeout)
        finally:
            # Preserve the request gap even when a provider request times out.
            time.sleep(REQUEST_PAUSE_SECONDS)
        response.raise_for_status()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"RIPE response exceeded the {MAX_RESPONSE_BYTES}-byte bound")
        body = response.json()
        # Atlas measurement-results endpoints can return a bare array while
        # discovery endpoints use the paginated {results, next} envelope.
        if isinstance(body, list):
            if len(body) > row_limit:
                raise RuntimeError(
                    f"RIPE result array exceeds the configured {row_limit}-row bound"
                )
            yield from body
            return
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise TypeError("Unexpected RIPE Atlas paginated response")
        row_count += len(body["results"])
        if row_count > row_limit:
            raise RuntimeError(
                f"RIPE paginated result exceeded the configured {row_limit}-row bound"
            )
        yield from body["results"]
        nxt = body.get("next")
        if not nxt:
            return
        url, params = nxt, {}
    raise RuntimeError(f"RIPE Atlas pagination exceeded bounded page limit {page_limit}")


def fetch(
    days: int = 14,
    out: Path | None = None,
    cache_dir: Path | None = None,
    *,
    client: httpx.Client | None = None,
    page_limit: int = 20,
    max_measurements: int = 5,
    max_probes: int = 5,
    deadline_seconds: float = 300.0,
) -> pd.DataFrame:
    """Fetch daily RIPE snapshots for selected Pakistani probes and public ping measurements."""
    if (
        not 1 <= days <= 30
        or not 1 <= max_measurements <= 20
        or not 1 <= max_probes <= 20
        or not 1 <= deadline_seconds <= 1800
    ):
        raise ValueError("days must be 1..30; probe and measurement limits must be 1..20")
    cache_dir = cache_dir or Path("data/raw/ripe/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    own = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={"User-Agent": "NetCortex-simgen/0.1"},
    )
    deadline = time.monotonic() + deadline_seconds
    try:
        probes = list(
            _pages(
                client,
                f"{API}/probes/",
                {"country_code": "PK", "status": 1, "page_size": 3},
                page_limit,
                deadline=deadline,
            )
        )
        chosen = _diverse_probes(probes, max_probes)
        ids = [int(p["id"]) for p in chosen if p.get("id") is not None]
        asns = {
            int(p["id"]): p.get("asn_v4") or p.get("asn_v6")
            for p in chosen
            if p.get("id") is not None
        }
        if not ids:
            frame = pd.DataFrame(
                columns=[
                    "time",
                    "site_id",
                    "target",
                    "rtt_ms",
                    "jitter_ms",
                    "loss_pct",
                    "source",
                ]
            )
            report = {
                "status": "no_active_probes",
                "days_requested": days,
                "probe_ids": [],
                "measurement_ids": [],
                "daily_measurement_requests": 0,
                "completed_daily_measurement_requests": 0,
                "failed_daily_measurement_requests": [],
            }
            frame.attrs["ripe_fetch_report"] = report
            if out:
                out.parent.mkdir(parents=True, exist_ok=True)
                frame.to_parquet(out, index=False)
                out.with_name(out.stem + ".fetch-report.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
            return frame
        measurements = list(
            _pages(
                client,
                f"{API}/measurements/",
                {"type": "ping", "is_public": "true", "status": 2, "page_size": 2},
                page_limit,
                deadline=deadline,
            )
        )
        measurement_ids = list(
            dict.fromkeys(int(m["id"]) for m in measurements if m.get("id") is not None)
        )[:max_measurements]
        targets = {
            int(m["id"]): m.get("target_ip") or m.get("target")
            for m in measurements
            if m.get("id") is not None
        }
        # Use completed UTC days so each successful result snapshot is cacheable.
        now = int(time.time() // 86400 * 86400)
        begin = now - days * 86400
        selected_probes = sorted(ids)
        probe_hash = hashlib.sha256(
            ",".join(map(str, selected_probes)).encode("ascii")
        ).hexdigest()[:12]
        report: dict[str, Any] = {
            "status": "complete" if measurement_ids else "no_measurements",
            "days_requested": days,
            "window_start": begin,
            "window_end_exclusive": now,
            "probe_ids": selected_probes,
            "measurement_ids": measurement_ids,
            "daily_measurement_requests": 0,
            "completed_daily_measurement_requests": 0,
            "failed_daily_measurement_requests": [],
            "days": {},
        }
        rows = []
        selected_counts = {mid: 0 for mid in measurement_ids}
        for mid in measurement_ids:
            for day_index in range(days):
                start = begin + day_index * 86400
                stop = start + 86400
                day_key = time.strftime("%Y-%m-%d", time.gmtime(start))
                day = report["days"].setdefault(
                    day_key,
                    {"status": "complete", "measurements": {}, "errors": [], "selected_rows": 0},
                )
                report["daily_measurement_requests"] += 1
                cache = cache_dir / f"measurement-{mid}-{start}-{stop}-probes-{probe_hash}.json"
                try:
                    if cache.exists():
                        items = json.loads(cache.read_text(encoding="utf-8"))
                        if not isinstance(items, list):
                            raise ValueError("cached RIPE result is not a list")
                    else:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                "RIPE fetch deadline elapsed before daily result request"
                            )
                        items = list(
                            _pages(
                                client,
                                f"{API}/measurements/{mid}/results/",
                                {
                                    "start": start,
                                    "stop": stop,
                                    "probe_ids": ",".join(map(str, selected_probes)),
                                    "page_size": 1000,
                                },
                                page_limit,
                                deadline=deadline,
                                row_limit=MAX_RAW_RESULT_ROWS_PER_DAY,
                            )
                        )
                        temporary = cache.with_suffix(cache.suffix + ".part")
                        temporary.write_text(json.dumps(items), encoding="utf-8")
                        temporary.replace(cache)
                    report["completed_daily_measurement_requests"] += 1
                    selected = []
                    for item in items:
                        try:
                            probe_id = int(item.get("prb_id"))
                        except (TypeError, ValueError):
                            continue
                        if probe_id in asns:
                            selected.append((item, probe_id))
                    remaining = MAX_SELECTED_ROWS_PER_MEASUREMENT - selected_counts[mid]
                    if len(selected) > remaining:
                        warnings.warn(
                            f"RIPE measurement {mid} exceeded its "
                            f"{MAX_SELECTED_ROWS_PER_MEASUREMENT}-row "
                            "selection bound; retaining the earliest bounded sample",
                            stacklevel=2,
                        )
                        selected = selected[: max(remaining, 0)]
                    selected_counts[mid] += len(selected)
                    day["measurements"][str(mid)] = {
                        "status": "complete",
                        "raw_rows": len(items),
                        "selected_probe_rows": len(selected),
                    }
                    day["selected_rows"] += len(selected)
                    for item, probe_id in selected:
                        parsed = parse_result(
                            {
                                **item,
                                "msm_id": mid,
                                "probe_asn": asns.get(probe_id),
                                "measurement_target": targets.get(mid),
                                "target_role": "unmapped_ripe_public_ping",
                            }
                        )
                        if parsed:
                            rows.append(parsed)
                except (
                    httpx.HTTPError,
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                    TimeoutError,
                ) as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    day["status"] = "partial" if day["measurements"] else "failed"
                    day["errors"].append({"measurement_id": mid, "error": message})
                    day["measurements"][str(mid)] = {"status": "failed", "error": message}
                    report["failed_daily_measurement_requests"].append(
                        {"date": day_key, "measurement_id": mid, "error": message}
                    )
        if report["failed_daily_measurement_requests"]:
            report["status"] = (
                "partial" if report["completed_daily_measurement_requests"] else "failed"
            )
        for day in report["days"].values():
            outcomes = [item["status"] for item in day["measurements"].values()]
            failures = outcomes.count("failed")
            successes = outcomes.count("complete")
            if failures and successes:
                day["status"] = "partial"
            elif failures:
                day["status"] = "failed"
            elif successes:
                day["status"] = "complete"
            else:
                day["status"] = "no_measurements"
        frame = pd.DataFrame(rows)
        frame.attrs["ripe_fetch_report"] = report
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(out, index=False)
            report_path = out.with_name(out.stem + ".fetch-report.json")
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if (
            report["daily_measurement_requests"]
            and not report["completed_daily_measurement_requests"]
        ):
            raise RuntimeError(
                "All RIPE daily result requests failed; inspect "
                f"{out.with_name(out.stem + '.fetch-report.json') if out else 'the fetch report'}"
            )
        return frame
    finally:
        if own:
            client.close()
