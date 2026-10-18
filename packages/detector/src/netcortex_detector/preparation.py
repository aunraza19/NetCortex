"""Prepare and load detector-owned TRAIN/VALIDATION state for public detect()."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from netcortex_core import ModuleUnavailable, Settings, get_settings

from netcortex_detector.engine import (
    CAUSES,
    _identity_target_roles,
    build_features,
)

ARTIFACT_FORMAT = "netcortex-detector-training"
ARTIFACT_VERSION = 1
DEFAULT_THRESHOLD = 0.7
NORMAL_REFERENCE_LIMIT = 3


@dataclass(frozen=True)
class _PreparedDetector:
    backend: Any
    threshold: float
    artifact_path: Path
    artifact_digest: str
    mode: str
    configuration_digest: str
    backend_factory_id: int


_prepared: _PreparedDetector | None = None


def prepare_detector(cases_dir: Path, out: Path) -> Path:
    """Build a data-only artifact from TRAIN and normal VALIDATION case packs."""
    cases_dir = Path(cases_dir).resolve()
    train_paths = sorted((cases_dir / "train").glob("*.json"))
    validation_paths = sorted((cases_dir / "validation").glob("*.json"))
    if not train_paths or not validation_paths:
        raise ModuleUnavailable("TRAIN and VALIDATION case files are required")

    train_cases = [_load_case(path, cases_dir, "train") for path in train_paths]
    validation_cases = [_load_case(path, cases_dir, "validation") for path in validation_paths]
    _validate_case_boundaries(train_cases, validation_cases)

    train_columns, train_rows, train_labels = _feature_rows(train_cases)
    if not train_rows:
        raise ModuleUnavailable("TRAIN cases produced no feature snapshots")
    normal_train = [
        row for row, label in zip(train_rows, train_labels, strict=True) if label == "normal"
    ]
    if len(normal_train) < 5:
        raise ModuleUnavailable("at least five normal TRAIN snapshots are required")
    if len(set(train_labels)) < 2:
        raise ModuleUnavailable("TRAIN cases must contain at least two cause classes")

    _, validation_rows, validation_labels = _feature_rows(validation_cases, columns=train_columns)
    normal_validation = [
        row
        for row, label in zip(validation_rows, validation_labels, strict=True)
        if label == "normal"
    ][:NORMAL_REFERENCE_LIMIT]
    if len(normal_validation) < 3:
        raise ModuleUnavailable("at least three normal VALIDATION snapshots are required")

    payload = {
        "format": ARTIFACT_FORMAT,
        "version": ARTIFACT_VERSION,
        "feature_columns": train_columns,
        "train_features": train_rows,
        "train_labels": train_labels,
        "normal_train_features": normal_train,
        "normal_validation_features": normal_validation,
        "threshold": DEFAULT_THRESHOLD,
        "threshold_note": "fixed plumbing default; not an accuracy-calibrated operating point",
        "normal_reference_note": (
            f"first {len(normal_validation)} normal VALIDATION snapshots; plumbing reference only"
        ),
        "provenance": {
            "train_case_ids": [case["case_id"] for case, _, _ in train_cases],
            "validation_case_ids": [case["case_id"] for case, _, _ in validation_cases],
            "train_seeds": [case["seed"] for case, _, _ in train_cases],
            "validation_seeds": [case["seed"] for case, _, _ in validation_cases],
            "train_windows": [_case_bounds(case) for case, _, _ in train_cases],
            "validation_windows": [_case_bounds(case) for case, _, _ in validation_cases],
        },
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    return out


def configure_detector(
    artifact: Path,
    *,
    settings: Settings | None = None,
    backend_factory: Callable[..., Any] | None = None,
) -> Any:
    """Fit and cache the real provider from a validated data-only artifact."""
    global _prepared
    artifact_path = Path(artifact).resolve()
    try:
        content = artifact_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        payload = json.loads(content)
        columns, train, labels, normal_train, normal_validation, threshold = _validate_artifact(
            payload
        )
    except ModuleUnavailable:
        _prepared = None
        raise
    except Exception as exc:
        _prepared = None
        raise ModuleUnavailable(
            f"detector training artifact is invalid ({type(exc).__name__})"
        ) from exc

    configured = settings or get_settings()
    mode = configured.tabpfn_mode
    token = configured.tabpfn_token.get_secret_value() if configured.tabpfn_token else None
    configuration_digest = hashlib.sha256(
        json.dumps(
            {
                "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest()
                if token is not None
                else None,
                "timeout_s": configured.http_timeout_s,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if _prepared and (
        _prepared.artifact_path == artifact_path
        and _prepared.artifact_digest == digest
        and _prepared.mode == mode
        and _prepared.configuration_digest == configuration_digest
        and (backend_factory is None or _prepared.backend_factory_id == id(backend_factory))
    ):
        return _prepared.backend

    if backend_factory is None:
        from netcortex_detector.providers import TabPFNBackend

        backend_factory = TabPFNBackend
    try:
        backend = backend_factory(mode, access_token=token, timeout_s=configured.http_timeout_s)
        if str(getattr(backend, "provenance", "")).startswith("fixture:"):
            raise ModuleUnavailable("startup preparation requires a real provider backend")
        train_frame = pd.DataFrame(train, columns=columns)
        normal_train_frame = pd.DataFrame(normal_train, columns=columns)
        train_labels = [str(label) for label in labels]
        backend.fit_cause_model(train_frame, train_labels)
        backend.fit_anomaly(normal_train_frame)
        validation_vectors = [pd.Series(row, index=columns) for row in normal_validation]
        if hasattr(backend, "raw_anomaly_batch"):
            validation_scores = backend.raw_anomaly_batch(validation_vectors)
        else:
            validation_scores = [backend.raw_anomaly(vector) for vector in validation_vectors]
        backend.set_anomaly_reference(validation_scores)
    except ModuleUnavailable:
        _prepared = None
        raise
    except Exception as exc:
        _prepared = None
        raise ModuleUnavailable(f"detector provider setup failed ({type(exc).__name__})") from exc

    _prepared = _PreparedDetector(
        backend=backend,
        threshold=threshold,
        artifact_path=artifact_path,
        artifact_digest=digest,
        mode=mode,
        configuration_digest=configuration_digest,
        backend_factory_id=id(backend_factory),
    )
    return backend


def get_prepared_detector() -> tuple[Any, float] | None:
    """Return the process-cached backend and fixed threshold, if startup configured it."""
    if _prepared is None:
        return None
    return _prepared.backend, _prepared.threshold


def clear_prepared_detector() -> None:
    """Clear the process cache; primarily useful for isolated application lifecycles/tests."""
    global _prepared
    _prepared = None


def _load_case(path: Path, cases_root: Path, expected_split: str):
    split_root = (cases_root / expected_split).resolve()
    if not split_root.is_relative_to(cases_root):
        raise ModuleUnavailable("split directory escapes the case root")
    if not path.resolve().is_relative_to(split_root):
        raise ModuleUnavailable("case path escapes its split directory")
    try:
        case = json.loads(path.read_text(encoding="utf-8"))
        if case.get("split") != expected_split:
            raise ValueError("case split does not match its directory")
        case_id = str(case["case_id"])
        site_id = str(case["site_id"])
        label = str(case["expected"]["cause"])
        seed = int(case["seed"])
        if not case_id or not site_id or label not in CAUSES:
            raise ValueError("case metadata is invalid")
        start, end = _case_bounds(case)
        folder = path.parent.resolve()
        observations = case["observations"]
        frames = []
        for key in ("probe", "iface"):
            observation_path = (folder / observations[key]).resolve()
            if not observation_path.is_relative_to(folder):
                raise ValueError("observation path escapes its split directory")
            frames.append(pd.read_parquet(observation_path))
        probes, interfaces = frames
        features = build_features(
            probes,
            interfaces,
            site_id=site_id,
            as_of=case["as_of"],
            target_roles=_identity_target_roles(probes),
        )
        if features.empty:
            raise ValueError("case produced no feature snapshots")
        row = features.iloc[-1]
        row = pd.to_numeric(row, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return (
            {"case_id": case_id, "site_id": site_id, "seed": seed, "start": start, "end": end},
            row,
            label,
        )
    except ModuleUnavailable:
        raise
    except Exception as exc:
        raise ModuleUnavailable(f"{expected_split} case is invalid ({type(exc).__name__})") from exc


def _case_bounds(case: dict[str, Any]) -> tuple[str, str]:
    start = pd.Timestamp(case.get("case_start", case.get("start")))
    end = pd.Timestamp(case.get("as_of", case.get("end")))
    if start.tzinfo is None or end.tzinfo is None or start > end:
        raise ValueError("case time bounds must be ordered and timezone-aware")
    return start.tz_convert("UTC").isoformat(), end.tz_convert("UTC").isoformat()


def _validate_case_boundaries(train_cases: list[Any], validation_cases: list[Any]) -> None:
    cases = [*train_cases, *validation_cases]
    ids = [case[0]["case_id"] for case in cases]
    seeds = [case[0]["seed"] for case in cases]
    if len(ids) != len(set(ids)) or len(seeds) != len(set(seeds)):
        raise ModuleUnavailable("TRAIN and VALIDATION case IDs and seeds must be distinct")
    for index, (left, _, _) in enumerate(cases):
        for right, _, _ in cases[index + 1 :]:
            if left["start"] <= right["end"] and right["start"] <= left["end"]:
                raise ModuleUnavailable("TRAIN and VALIDATION case time ranges overlap")


def _feature_rows(cases: list[Any], columns: list[str] | None = None):
    frame = pd.DataFrame([row for _, row, _ in cases]).replace([np.inf, -np.inf], np.nan)
    if columns is None:
        columns = sorted(str(column) for column in frame.columns)
    frame = frame.reindex(columns=columns).fillna(0.0)
    rows = frame.to_numpy(dtype=float).tolist()
    labels = [label for _, _, label in cases]
    return columns, rows, labels


def _validate_artifact(payload: Any):
    if not isinstance(payload, dict):
        raise ModuleUnavailable("detector training artifact must be an object")
    if payload.get("format") != ARTIFACT_FORMAT or payload.get("version") != ARTIFACT_VERSION:
        raise ModuleUnavailable("detector training artifact format or version is unsupported")
    columns = payload.get("feature_columns")
    train = payload.get("train_features")
    labels = payload.get("train_labels")
    normal_train = payload.get("normal_train_features")
    normal_validation = payload.get("normal_validation_features")
    threshold = payload.get("threshold")
    provenance = payload.get("provenance")
    if (
        not isinstance(columns, list)
        or not columns
        or len(columns) != len(set(columns))
        or not isinstance(train, list)
        or not isinstance(labels, list)
        or len(train) != len(labels)
        or not isinstance(normal_train, list)
        or len(normal_train) < 5
        or not isinstance(normal_validation, list)
        or len(normal_validation) < 3
        or not isinstance(threshold, (int, float))
        or not np.isfinite(threshold)
        or not 0 <= threshold <= 1
        or not isinstance(provenance, dict)
    ):
        raise ModuleUnavailable("detector training artifact fields are invalid")
    if not train or any(label not in CAUSES for label in labels) or len(set(labels)) < 2:
        raise ModuleUnavailable("detector training artifact labels are invalid")
    for matrix in (train, normal_train, normal_validation):
        values = np.asarray(matrix, dtype=float)
        if values.shape != (len(matrix), len(columns)) or not np.isfinite(values).all():
            raise ModuleUnavailable("detector training artifact feature matrix is invalid")
    split_metadata = {}
    for split in ("train", "validation"):
        ids = provenance.get(f"{split}_case_ids")
        seeds = provenance.get(f"{split}_seeds")
        windows = provenance.get(f"{split}_windows")
        if (
            not isinstance(ids, list)
            or not isinstance(seeds, list)
            or not isinstance(windows, list)
        ):
            raise ModuleUnavailable("detector training artifact provenance is incomplete")
        if len(ids) != len(set(ids)) or len(seeds) != len(set(seeds)) or len(ids) != len(seeds):
            raise ModuleUnavailable("detector training artifact provenance is inconsistent")
        if any(not isinstance(value, str) or not value for value in ids):
            raise ModuleUnavailable("detector training artifact case IDs are invalid")
        if any(not isinstance(value, int) for value in seeds):
            raise ModuleUnavailable("detector training artifact seeds are invalid")
        if len(windows) != len(ids):
            raise ModuleUnavailable("detector training artifact time ranges are inconsistent")
        split_metadata[split] = (ids, seeds, windows)
    train_ids, train_seeds, train_windows = split_metadata["train"]
    validation_ids, validation_seeds, validation_windows = split_metadata["validation"]
    if set(train_ids) & set(validation_ids) or set(train_seeds) & set(validation_seeds):
        raise ModuleUnavailable("detector training artifact TRAIN and VALIDATION overlap")
    parsed_windows = []
    for split, ranges in (("train", train_windows), ("validation", validation_windows)):
        split_ranges = []
        for start_text, end_text in ranges:
            start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
            if start.tzinfo is None or end.tzinfo is None or start > end:
                raise ModuleUnavailable("detector training artifact time ranges are invalid")
            split_ranges.append((start, end))
        parsed_windows.append((split, split_ranges))
    for index, (split, left_ranges) in enumerate(parsed_windows):
        for other_split, right_ranges in parsed_windows[index:]:
            for left_start, left_end in left_ranges:
                for right_start, right_end in right_ranges:
                    if split == other_split and left_start == right_start and left_end == right_end:
                        continue
                    if left_start <= right_end and right_start <= left_end:
                        raise ModuleUnavailable("detector training artifact time ranges overlap")
    if len(train) != len(train_ids) or len(normal_train) != labels.count("normal"):
        raise ModuleUnavailable("detector training artifact row counts are inconsistent")
    return columns, train, labels, normal_train, normal_validation, float(threshold)
