"""Bounded real TabPFN timing check on full in-memory sim-tower telemetry; no DB writes."""

import contextlib
import io
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path

import pandas as pd
from netcortex_core import Cause, MetricsWindow, Settings
from netcortex_detector import configure_detector, detect
from netcortex_simgen.simulator import _runtime_rows

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    helpers = run_path(str(ROOT / "eval/gate2.py"))
    settings = Settings(http_timeout_s=20)
    secrets = helpers["_secret_values"](settings)
    captured = io.StringIO()
    report = {
        "gate": "Full sim-tower real-provider contract and timing canary",
        "status": "failed",
        "site_id": "sim-tower",
        "provider_mode": settings.tabpfn_mode,
        "injected_cause": "heavy_user",
        "timings_seconds": {},
        "limitations": "in-memory observations, no DB/Temporal; no accuracy claim",
    }
    started = time.perf_counter()
    try:
        print("Runtime canary: configuring real provider", flush=True)
        before = time.perf_counter()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            backend = configure_detector(
                ROOT / "data/generated/gate2/training.json", settings=settings
            )
        report["timings_seconds"]["setup"] = time.perf_counter() - before
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        parts = [
            _runtime_rows(now - timedelta(minutes=150), now - timedelta(minutes=3), None, 901),
            _runtime_rows(
                now - timedelta(minutes=3), now + timedelta(seconds=1), Cause.HEAVY_USER, 902
            ),
        ]
        frames = [
            pd.DataFrame([row.model_dump(mode="python") for part in parts for row in part[i]])
            for i in range(3)
        ]
        cutoff = now - timedelta(minutes=30)

        def window(start, end):
            selected = [
                frame[(frame.time > start) & (frame.time <= end)].copy() for frame in frames
            ]
            return MetricsWindow(
                as_of=end,
                probe_metrics=selected[0],
                iface_metrics=selected[1],
                subscriber_metrics=selected[2],
            )

        current = window(cutoff, now)
        history = window(now - timedelta(minutes=150, seconds=1), cutoff)
        print("Runtime canary: detecting all sim-tower probe/interface series", flush=True)
        before = time.perf_counter()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            result = detect("sim-tower", current, history)
        report["timings_seconds"]["detect"] = time.perf_counter() - before
        helpers["_validate_result"](
            result, settings=settings, as_of=now, expected_model=backend.provenance
        )
        report["result"] = {
            "model": result.model,
            "mode": result.mode,
            "cause": result.cause_guess.value,
            "score": result.score,
            "cause_confidence": result.cause_confidence,
            "series_count": len(result.series),
            "horizons_each": [len(s.points) for s in result.series],
            "cause_matches_injection": result.cause_guess == Cause.HEAVY_USER,
        }
        report["contract_passed"] = True
        report["under_110_second_inference_budget"] = report["timings_seconds"]["detect"] < 110
        report["status"] = (
            "passed" if report["under_110_second_inference_budget"] else "latency_failed"
        )
    except Exception as exc:
        report["error_chain"] = helpers["_safe_error"](exc, secrets)
        report["error_locations"] = helpers["_safe_frames"](exc)
    report["timings_seconds"]["total"] = time.perf_counter() - started
    safe = helpers["_sanitize_tree"](report, secrets)
    output = ROOT / ".build-check/runtime-canary.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(safe, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Runtime canary {safe['status']}; sanitized report saved.")
    return 0 if safe["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
