from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from netcortex_detector.engine import DetectorConfig, DetectorUnavailable, run_engine
from netcortex_detector.providers import FixtureBackend, TabPFNBackend


def _model_inputs(backend: TabPFNBackend, train_path: Path, validation_path: Path):
    train = pd.read_parquet(train_path)
    validation = pd.read_parquet(validation_path)
    if "cause" not in train or "cause" not in validation:
        raise ValueError("train and validation feature Parquet files must have a cause column")
    train_labels = train.pop("cause").astype(str).tolist()
    validation_labels = validation.pop("cause").astype(str).tolist()
    if list(train.columns) != list(validation.columns):
        raise ValueError("train and validation feature columns must match in the same order")
    train = train.fillna(0)
    validation = validation.fillna(0)
    backend.fit_anomaly(train.loc[np.asarray(train_labels) == "normal"])
    normal_scores = [
        backend.raw_anomaly(validation.iloc[index])
        for index, label in enumerate(validation_labels)
        if label == "normal"
    ]
    backend.set_anomaly_reference(normal_scores)
    val_scores = [backend.anomaly(validation.iloc[index]) for index in range(len(validation))]
    return train, train_labels, val_scores, [label != "normal" for label in validation_labels]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one NetCortex detector evaluation window")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="use explicit fixture-only backend")
    mode.add_argument("--mode", choices=("cloud", "local"), help="use an actual TabPFN provider")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--probes", required=True, type=Path)
    parser.add_argument("--interfaces", required=True, type=Path)
    parser.add_argument("--as-of", required=True, help="timezone-aware ISO-8601 timestamp")
    parser.add_argument("--history-start", help="timezone-aware ISO-8601 timestamp")
    parser.add_argument("--train", type=Path, help="TRAIN feature Parquet with a cause column")
    parser.add_argument(
        "--validation", type=Path, help="VALIDATION feature Parquet with a cause column"
    )
    args = parser.parse_args()
    if bool(args.train) != bool(args.validation):
        parser.error("--train and --validation must be supplied together")
    try:
        probes, interfaces = pd.read_parquet(args.probes), pd.read_parquet(args.interfaces)
        backend = FixtureBackend() if args.mock else TabPFNBackend(args.mode)
        train_features = train_labels = None
        threshold = None
        if isinstance(backend, TabPFNBackend):
            if not args.train:
                raise ValueError(
                    "real inference requires TRAIN and VALIDATION feature Parquet inputs"
                )
            train_features, train_labels, val_scores, val_labels = _model_inputs(
                backend, args.train, args.validation
            )
            from netcortex_detector.thresholds import calibrate_threshold

            threshold = calibrate_threshold(
                val_scores, val_labels, [args.site_id] * len(val_scores)
            )
        result = run_engine(
            probes,
            interfaces,
            site_id=args.site_id,
            as_of=args.as_of,
            history_start=args.history_start,
            backend=backend,
            config=DetectorConfig(),
            training_features=train_features,
            training_labels=train_labels,
            anomaly_threshold=threshold,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["status"] == "ok" else 2
    except (DetectorUnavailable, ValueError, OSError) as exc:
        print(f"detector unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
