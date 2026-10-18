from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from netcortex_core import (
    Cause,
    DetectionResult,
    ForecastPoint,
    MetricsWindow,
    SeriesForecast,
)
from netcortex_detector.engine import (
    DetectorConfig,
    DetectorUnavailable,
    _forecast_series_key,
    build_features,
    run_engine,
)
from netcortex_detector.providers import FixtureBackend, TabPFNBackend
from netcortex_detector.thresholds import calibrate_threshold, normal_site_days

ROOT = Path(__file__).resolve().parents[1]


def _load_case(path: Path) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    case = json.loads(path.read_text(encoding="utf-8"))
    folder = path.parent
    root = folder.resolve()
    observation_paths = {}
    for key in ("probe", "iface"):
        candidate = (folder / case["observations"][key]).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"case observation path escapes split directory: {key}")
        observation_paths[key] = candidate
    probes = pd.read_parquet(observation_paths["probe"])
    interfaces = pd.read_parquet(observation_paths["iface"])
    return case, probes, interfaces


def _feature_rows(paths: list[Path]) -> tuple[list[pd.Series], list[str]]:
    rows, labels = [], []
    for path in paths:
        case, probes, interfaces = _load_case(path)
        features = build_features(probes, interfaces, site_id=case["site_id"], as_of=case["as_of"])
        if not features.empty:
            rows.append(features.iloc[-1])
            labels.append(case["expected"]["cause"])
    frame = pd.DataFrame(rows).fillna(0)
    return [frame.iloc[i] for i in range(len(frame))], labels


def _verify_splits(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    test: list[dict[str, Any]],
) -> None:
    for split, cases in (("train", train), ("validation", validation), ("test", test)):
        if any(case["split"] != split for case in cases):
            raise ValueError(f"case metadata contains wrong split under {split}/")
    ids = [{case["case_id"] for case in split} for split in (train, validation, test)]
    seeds = [{case["seed"] for case in split} for split in (train, validation, test)]
    windows = [
        [(pd.Timestamp(case["case_start"]), pd.Timestamp(case["as_of"])) for case in split]
        for split in (train, validation, test)
    ]
    for label, values in (
        ("case IDs", ids),
        ("seeds", seeds),
        ("time windows", windows),
    ):
        if label != "time windows" and (
            values[0] & values[1] or values[0] & values[2] or values[1] & values[2]
        ):
            raise ValueError(f"{label} overlap across train, validation and test")
    for left in range(len(windows)):
        for right in range(left + 1, len(windows)):
            overlap = any(
                a_start <= b_end and b_start <= a_end
                for a_start, a_end in windows[left]
                for b_start, b_end in windows[right]
            )
            if overlap:
                raise ValueError("case time windows overlap across train, validation and test")


def _as_detection_result(result: dict[str, Any], mode: str) -> DetectionResult:
    grouped: dict[str, list[ForecastPoint]] = {}
    for row in result.get("forecasts", []):
        grouped.setdefault(_forecast_series_key(str(row["metric"])), []).append(
            ForecastPoint(
                time=pd.Timestamp(row["target_time"]).to_pydatetime(),
                p10=float(row["p10"]),
                p50=float(row["p50"]),
                p90=float(row["p90"]),
            )
        )
    series = [
        SeriesForecast(series_key=key, points=points) for key, points in sorted(grouped.items())
    ]
    provenance = str(result.get("provenance", ""))
    fixture = provenance.startswith("fixture:")
    return DetectionResult(
        is_anomaly=bool(result["is_anomaly"]),
        score=float(result["anomaly_score"]),
        cause_guess=Cause(result["cause"]),
        cause_confidence=float(result["cause_confidence"]),
        evidence=result.get("evidence", []),
        series=series,
        model="fixture_persistence" if fixture else provenance,
        mode="mock" if fixture else mode,
    )


def evaluate(
    cases_dir: Path,
    *,
    mode: str,
    out: Path,
    limit: int | None = None,
    investigator: Any | None = None,
    params_validator: Any | None = None,
    chr_checker: Any | None = None,
    run_agent: bool = False,
    run_chr: bool = False,
) -> dict[str, Any]:
    if run_agent:
        from netcortex_agent.agent import investigate
        from netcortex_fixes import validate

        async def investigate_case(result: dict[str, Any], case, probes, interfaces):
            detection = _as_detection_result(result, mode)
            window = MetricsWindow(
                as_of=pd.Timestamp(case["as_of"]).to_pydatetime(),
                probe_metrics=probes,
                iface_metrics=interfaces,
            )
            report = await investigate(case["site_id"], detection, window)
            return report.model_dump(mode="json")

        if investigator is None:
            investigator = investigate_case
        if params_validator is None:

            def validate_report(report):
                validate(report["template_id"], report.get("template_params", {}))
                return True

            params_validator = validate_report
    if run_chr:
        from netcortex_fixes import RouterClient, dry_run

        client = RouterClient.chr()
        if chr_checker is None:

            def check_on_chr(report):
                return dry_run(report["template_id"], report.get("template_params", {}), client).ok

            chr_checker = check_on_chr
    split_paths = {
        name: sorted((cases_dir / name).glob("*.json")) for name in ("train", "validation", "test")
    }
    if any(not paths for paths in split_paths.values()):
        raise FileNotFoundError("expected train/, validation/, and test/ JSON case files")
    split_data = {
        name: [_load_case(path)[0] for path in paths] for name, paths in split_paths.items()
    }
    _verify_splits(split_data["train"], split_data["validation"], split_data["test"])
    backend = FixtureBackend() if mode == "mock" else TabPFNBackend(mode)
    train_vectors, train_labels = _feature_rows(split_paths["train"])
    train_frame = pd.DataFrame(train_vectors).fillna(0)
    setup_error = None
    if isinstance(backend, TabPFNBackend):
        try:
            normal_train = train_frame.loc[np.asarray(train_labels) == "normal"]
            backend.fit_anomaly(normal_train)
            normal_reference = []
            for path in split_paths["validation"]:
                case, probes, interfaces = _load_case(path)
                if case["expected"]["cause"] != "normal":
                    continue
                features = build_features(
                    probes, interfaces, site_id=case["site_id"], as_of=case["as_of"]
                )
                if not features.empty:
                    normal_reference.append(backend.raw_anomaly(features.iloc[-1]))
            backend.set_anomaly_reference(normal_reference)
        except DetectorUnavailable as exc:
            setup_error = str(exc)
    validation_scores: list[float] = []
    validation_labels: list[bool] = []
    validation_sites: list[str] = []
    validation_normal_windows: list[tuple[str, str, str]] = []
    validation_unavailable = 0
    # Validation calibrates score threshold only; no test data participates.
    for path in split_paths["validation"]:
        case, probes, interfaces = _load_case(path)
        if setup_error is not None:
            validation_unavailable += 1
            continue
        try:
            result = run_engine(
                probes,
                interfaces,
                site_id=case["site_id"],
                as_of=case["as_of"],
                history_start=case["history_window"]["start"],
                backend=backend,
                config=DetectorConfig(),
                training_features=train_frame,
                training_labels=train_labels,
                anomaly_threshold=1.0,
            )
        except DetectorUnavailable:
            validation_unavailable += 1
            continue
        if result["status"] == "ok":
            validation_scores.append(result["anomaly_score"])
            is_normal = case["expected"]["cause"] == "normal"
            validation_labels.append(not is_normal)
            validation_sites.append(case["site_id"])
            if is_normal:
                validation_normal_windows.append(
                    (
                        case["site_id"],
                        case["detection_window"]["start"],
                        case["detection_window"]["end_inclusive"],
                    )
                )
    threshold = calibrate_threshold(
        validation_scores,
        validation_labels,
        validation_sites,
        exposure_intervals=validation_normal_windows,
    )
    selected = split_paths["test"][:limit] if limit else split_paths["test"]
    results = []
    for path in selected:
        case, probes, interfaces = _load_case(path)
        started = time.perf_counter()
        try:
            if setup_error is not None:
                raise DetectorUnavailable(setup_error)
            result = run_engine(
                probes,
                interfaces,
                site_id=case["site_id"],
                as_of=case["as_of"],
                history_start=case["history_window"]["start"],
                backend=backend,
                training_features=train_frame,
                training_labels=train_labels,
                anomaly_threshold=threshold,
            )
            status = result["status"]
        except DetectorUnavailable as exc:
            result, status = (
                {"error": str(exc), "provenance": backend.provenance},
                "unavailable",
            )
        agent_result = None
        hook_error = None
        if investigator is not None and status == "ok":
            try:
                agent_result = (
                    investigator(result, case, *_load_case(path)[1:])
                    if run_agent and investigator is not None
                    else investigator(result)
                )
                if asyncio.iscoroutine(agent_result):
                    agent_result = asyncio.run(agent_result)
            except Exception as exc:  # noqa: BLE001 - injected integration hook boundary
                hook_error = f"investigator unavailable ({type(exc).__name__})"
        params_valid = None
        chr_pass = None
        if isinstance(agent_result, dict):
            if params_validator is not None:
                try:
                    params_valid = bool(params_validator(agent_result))
                except Exception as exc:  # noqa: BLE001 - injected integration hook boundary
                    hook_error = f"parameter validation unavailable ({type(exc).__name__})"
            if chr_checker is not None:
                try:
                    chr_pass = bool(chr_checker(agent_result))
                except Exception as exc:  # noqa: BLE001 - injected integration hook boundary
                    hook_error = f"CHR check unavailable ({type(exc).__name__})"
        results.append(
            {
                "case_id": case["case_id"],
                "site_id": case["site_id"],
                "detection_start": case["detection_window"]["start"],
                "detection_end": case["detection_window"]["end_inclusive"],
                "expected_cause": case["expected"]["cause"],
                "predicted_cause": result.get("cause"),
                "expected_template": case["expected"].get("template_id"),
                "agent_cause": agent_result.get("likely_cause", agent_result.get("cause"))
                if isinstance(agent_result, dict)
                else None,
                "predicted_template": agent_result.get("template_id")
                if isinstance(agent_result, dict)
                else None,
                "params_valid": params_valid,
                "chr_pass": chr_pass,
                "hook_error": hook_error,
                "is_anomaly": result.get("is_anomaly"),
                "status": status,
                "seconds": time.perf_counter() - started,
                "provenance": result.get("provenance"),
            }
        )
    scored = [r for r in results if r["status"] == "ok"]
    positives = [r for r in scored if r["expected_cause"] != "normal"]
    tp = sum(bool(r["is_anomaly"]) for r in positives)
    fp = sum(bool(r["is_anomaly"]) for r in scored if r["expected_cause"] == "normal")
    fn = len(positives) - tp
    cause_correct = sum(r["predicted_cause"] == r["expected_cause"] for r in scored)
    site_days = normal_site_days(
        (row["site_id"], row["detection_start"], row["detection_end"])
        for row in scored
        if row["expected_cause"] == "normal"
    )
    report = {
        "mode": mode,
        "provenance": backend.provenance,
        "requested_test_cases": len(selected),
        "available_test_cases": len(scored),
        "unavailable_cases": len(results) - len(scored),
        "cause_accuracy": cause_correct / len(scored) if scored else None,
        "cause_accuracy_denominator": len(scored),
        "event_precision": tp / (tp + fp) if tp + fp else None,
        "event_precision_denominator": tp + fp,
        "event_recall": tp / (tp + fn) if tp + fn else None,
        "event_recall_denominator": len(positives),
        "false_alerts_per_site_day": fp / site_days if site_days else None,
        "false_alerts_site_day_denominator": site_days,
        "detection_delay_minutes": None,
        "detection_delay_note": (
            "unavailable: runner scores one as_of snapshot per case; "
            "minute-by-minute replay is required"
        ),
        "median_seconds": statistics.median([r["seconds"] for r in scored]) if scored else None,
        "template_accuracy": _rate(
            [
                r["predicted_template"] == r["expected_template"]
                for r in results
                if r["predicted_template"] is not None
            ]
        ),
        "valid_params_rate": _rate(
            [r["params_valid"] for r in results if r["params_valid"] is not None]
        ),
        "chr_dry_run_pass_rate": _rate(
            [r["chr_pass"] for r in results if r["chr_pass"] is not None]
        ),
        "template_note": "measured from investigator integration"
        if any(r["predicted_template"] is not None for r in results)
        else "unavailable: no investigator result was returned",
        "params_note": "measured from injected validator hook"
        if any(r["params_valid"] is not None for r in results)
        else ("unavailable: no investigator parameters were returned for validation"),
        "chr_note": "measured from injected checker hook"
        if any(r["chr_pass"] is not None for r in results)
        else "unavailable: CHR dry-run was not executed or no investigator result was returned",
        "validation_score_count": len(validation_scores),
        "validation_unavailable_cases": validation_unavailable,
        "validation_normal_site_day_exposure": normal_site_days(validation_normal_windows),
        "frozen_threshold": threshold,
        "agent_cause_denominator": sum(r["agent_cause"] is not None for r in results),
        "agent_cause_accuracy": _rate(
            [
                r["agent_cause"] == r["expected_cause"]
                for r in results
                if r["agent_cause"] is not None
            ]
        ),
        "template_denominator": sum(r["predicted_template"] is not None for r in results),
        "template_accuracy_actual": _rate(
            [
                r["predicted_template"] == r["expected_template"]
                for r in results
                if r["predicted_template"] is not None
            ]
        ),
        "params_denominator": sum(r["params_valid"] is not None for r in results),
        "params_rate_actual": _rate(
            [r["params_valid"] for r in results if r["params_valid"] is not None]
        ),
        "chr_denominator": sum(r["chr_pass"] is not None for r in results),
        "chr_pass_rate_actual": _rate(
            [r["chr_pass"] for r in results if r["chr_pass"] is not None]
        ),
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_markdown(report), encoding="utf-8")
    return report


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _markdown(report: dict[str, Any]) -> str:
    fields = ("cause_accuracy", "event_precision", "event_recall", "median_seconds")
    false_alerts = report["false_alerts_per_site_day"]
    site_day_denominator = report["false_alerts_site_day_denominator"]
    agent_cause_accuracy = report["agent_cause_accuracy"]
    agent_cause_denominator = report["agent_cause_denominator"]
    fixture_disclaimer = (
        "Fixture results describe only the deterministic fixture backend. "
        "They are not TabPFN accuracy claims."
    )
    lines = [
        "# Detector evaluation",
        "",
        f"Mode: `{report['mode']}`",
        f"Provenance: {report['provenance']}",
        f"Test cases available: {report['available_test_cases']} / "
        f"{report['requested_test_cases']}",
        f"Unavailable cases: {report['unavailable_cases']}",
        "",
        "| Measure | Result |",
        "|---|---:|",
    ]
    for field in fields:
        lines.append(f"| {field} | {report[field]} |")
    lines += [
        "",
        f"Precision denominator: {report['event_precision_denominator']}",
        f"Recall denominator: {report['event_recall_denominator']}",
        f"False alerts/site-day: {false_alerts} (site-day denominator {site_day_denominator})",
        f"Detection delay: {report['detection_delay_minutes']} ({report['detection_delay_note']})",
        f"Validation score count: {report['validation_score_count']}",
        f"Validation unavailable cases: {report['validation_unavailable_cases']}",
        f"Validation normal exposure (site-days): {report['validation_normal_site_day_exposure']}",
        f"Frozen validation threshold: {report['frozen_threshold']}",
        "",
        f"Agent cause accuracy: {agent_cause_accuracy} (denominator {agent_cause_denominator})",
        f"Template accuracy: {report['template_accuracy']} "
        f"(denominator {report['template_denominator']}; {report['template_note']})",
        f"Valid parameter rate: {report['valid_params_rate']} "
        f"(denominator {report['params_denominator']}; {report['params_note']})",
        f"CHR dry-run pass rate: {report['chr_dry_run_pass_rate']} "
        f"(denominator {report['chr_denominator']}; {report['chr_note']})",
        "",
        *([fixture_disclaimer] if report["mode"] == "mock" else []),
        "",
        "## Cases",
        "",
        "| Case | Expected cause | Detector cause | Agent cause | Template | Params valid | "
        "CHR pass | Hook error | Anomaly | Status | Seconds |",
        "|---|---|---|---|---|---:|---:|---|---:|---|---:|",
    ]
    lines += [
        f"| {r['case_id']} | {r['expected_cause']} | {r['predicted_cause']} | "
        f"{r['agent_cause']} | {r['predicted_template']} | {r['params_valid']} | "
        f"{r['chr_pass']} | {r['hook_error']} | {r['is_anomaly']} | {r['status']} | "
        f"{r['seconds']:.3f} |"
        for r in report["results"]
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate NetCortex detector against held-out cases"
    )
    parser.add_argument("--cases", type=Path, default=ROOT / "eval" / "cases")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "detector.md")
    parser.add_argument("--mode", choices=("mock", "cloud", "local"), default="mock")
    parser.add_argument("--limit", type=int, help="limit test cases for a fixture smoke run")
    parser.add_argument("--with-agent", action="store_true", help="run Aun's Gemma investigator")
    parser.add_argument(
        "--chr-dry-run",
        action="store_true",
        help="apply and roll back fixes on the configured CHR",
    )
    args = parser.parse_args()
    if args.chr_dry_run and not args.with_agent:
        parser.error("--chr-dry-run requires --with-agent")
    report = evaluate(
        args.cases,
        mode=args.mode,
        out=args.out,
        limit=args.limit,
        run_agent=args.with_agent,
        run_chr=args.chr_dry_run,
    )
    print(f"Evaluated {report['available_test_cases']} available cases; report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
