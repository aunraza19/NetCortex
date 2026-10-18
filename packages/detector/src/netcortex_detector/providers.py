from __future__ import annotations

import os
import random
import sys
import warnings
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd

from netcortex_detector.engine import CAUSES, DetectorUnavailable, fingerprint

RAW_METRIC_PREFIXES = ("rtt_ms_", "loss_pct_", "iface_util_pct_")
LAG_PREFIXES = ("rtt_ms_", "jitter_ms_", "loss_pct_", "iface_")
DERIVED_SUFFIXES = ("_lag1", "_mean5", "_std5")
MAX_TRAINING_ROWS = 2048
ANOMALY_PERMUTATION_SEED = 73021
MAX_PARALLEL_FORECASTS = 8
FORECAST_INFERENCE_BUDGET_SECONDS = 90.0
_ANOMALY_PERMUTATION_LOCK = Lock()


def _array(frame: pd.DataFrame) -> np.ndarray:
    return (
        frame.select_dtypes(include=["number"])
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
        .to_numpy(dtype=float)
    )


def _bounded_horizon_rows(
    x_parts: list[pd.DataFrame], y_parts: list[pd.Series], max_rows: int
) -> tuple[pd.DataFrame, np.ndarray]:
    """Cap expanded training rows deterministically while retaining each horizon."""
    groups = [
        (x.reset_index(drop=True), y.reset_index(drop=True))
        for x, y in zip(x_parts, y_parts, strict=True)
    ]
    nonempty = [(x, y) for x, y in groups if len(x)]
    if len(nonempty) > max_rows:
        raise DetectorUnavailable("forecast row budget is too small to retain every horizon")
    base, remainder = divmod(max_rows, len(nonempty)) if nonempty else (0, 0)
    selected_x, selected_y = [], []
    for position, (x, y) in enumerate(nonempty):
        quota = min(len(x), base + (position < remainder))
        indices = np.linspace(0, len(x) - 1, quota, dtype=int) if quota else np.array([], dtype=int)
        selected_x.append(x.iloc[indices])
        selected_y.append(y.iloc[indices])
    if not selected_x:
        return pd.DataFrame(), np.array([], dtype=float)
    return pd.concat(selected_x, ignore_index=True), pd.concat(selected_y).to_numpy(dtype=float)


def _quantile_matrix(response: Any, horizons: int) -> np.ndarray:
    """Normalize documented quantile-first [q10, q50, q90] arrays to horizons x 3."""
    if isinstance(response, (list, tuple)) and len(response) == 3:
        columns = [np.asarray(values, dtype=float).reshape(-1) for values in response]
        if any(len(column) != horizons for column in columns):
            raise DetectorUnavailable(
                "TabPFN returned a quantile array with the wrong horizon count"
            )
        return np.column_stack(columns)
    values = np.asarray(response, dtype=float)
    if values.shape == (horizons, 3):
        return values
    if values.shape == (3, horizons):
        return values.T
    raise DetectorUnavailable("TabPFN returned quantiles with an unsupported shape")


def _validate_forecast_values(
    metric: str, low: float, median: float, high: float, horizon: int
) -> None:
    if horizon < 1 or horizon > 5:
        raise DetectorUnavailable("TabPFN returned an unsupported forecast horizon")
    if not np.isfinite([low, median, high]).all() or not low <= median <= high:
        raise DetectorUnavailable("TabPFN returned nonfinite or unordered quantiles")
    upper = 100.0 if metric.startswith(("loss_pct_", "iface_util_pct_")) else None
    if low < 0 or (upper is not None and high > upper):
        raise DetectorUnavailable("TabPFN forecast is outside physical metric bounds")


class FixtureBackend:
    """Deterministic offline backend. Results must be labelled fixture provenance."""

    provenance = "fixture: deterministic persistence/heuristic backend; no TabPFN inference"

    def forecasts(self, history: pd.DataFrame, horizon: int) -> list[dict[str, Any]]:
        numeric = history.select_dtypes(include=["number"]).tail(30)
        origin = pd.Timestamp(history.index.max())
        out = []
        for metric in (
            column
            for column in numeric.columns
            if column.startswith(RAW_METRIC_PREFIXES) and not column.endswith(DERIVED_SUFFIXES)
        ):
            values = numeric[metric].dropna().to_numpy(dtype=float)
            if not len(values):
                continue
            center = float(np.median(values[-5:]))
            spread = max(float(np.median(np.abs(values - np.median(values))) * 1.4826), 0.01)
            lower = 0.0
            upper = 100.0 if metric.startswith(("loss_pct_", "iface_util_pct_")) else np.inf
            for step in range(1, horizon + 1):
                out.append(
                    {
                        "metric": metric,
                        "made_at": origin.isoformat(),
                        "target_time": (
                            origin.floor("min") + pd.Timedelta(minutes=step)
                        ).isoformat(),
                        "horizon_minutes": step,
                        "p10": max(lower, center - 1.2816 * spread),
                        "p50": float(np.clip(center, lower, upper)),
                        "p90": min(upper, center + 1.2816 * spread),
                        "model": "fixture_persistence",
                    }
                )
        return out

    def cause(self, vector: pd.Series) -> tuple[str, float]:
        util = _first(vector, "iface_util_pct_")
        loss = max(
            (_first(vector, k) for k in vector.index if k.startswith("loss_pct_")), default=0.0
        )
        if util > 96 and loss > 2:
            return "uplink_congestion", 0.70
        if util < 10 and loss >= 99:
            return "uplink_down", 0.65
        if loss > 20:
            return "wireless_interference", 0.55
        return "normal", 0.55

    def anomaly(self, vector: pd.Series) -> float:
        util = _first(vector, "iface_util_pct_")
        loss = max(
            (_first(vector, k) for k in vector.index if k.startswith("loss_pct_")), default=0.0
        )
        return float(np.clip(max((util - 90) / 10, loss / 100), 0.0, 1.0))


def _first(vector: pd.Series, prefix: str) -> float:
    values = [
        float(value)
        for key, value in vector.items()
        if key.startswith(prefix) and np.isfinite(value)
    ]
    return values[0] if values else 0.0


class TabPFNBackend:
    """Cloud or local TabPFN 3.5 adapters with bounded inputs and cached fits."""

    supports_parallel_inference = True

    def __init__(self, mode: str, *, access_token: str | None = None, timeout_s: float = 30.0):
        if mode not in {"cloud", "local"}:
            raise ValueError("mode must be cloud or local")
        self.mode = mode
        self.access_token = access_token or os.getenv("TABPFN_TOKEN") or os.getenv("TABPFN_API_KEY")
        self.timeout_s = timeout_s
        self.provenance = f"tabpfn-{mode}:v3.5"
        self._models: dict[tuple[str, str], Any] = {}
        self._model_registry_lock = Lock()
        self._model_locks = tuple(Lock() for _ in range(64))
        self._model_classes: tuple[Any, Any] | None = None
        self._unsupervised: Any | None = None
        self._anomaly_columns: list[str] = []
        self._anomaly_reference: np.ndarray | None = None
        self._cause_features: pd.DataFrame | None = None
        self._cause_labels: list[str] | None = None
        self._unsupervised_module: Any | None = None

    def _imports(self) -> tuple[Any, Any]:
        if self._model_classes is not None:
            return self._model_classes
        try:
            if self.mode == "cloud":
                if not self.access_token:
                    raise DetectorUnavailable(
                        "TABPFN_TOKEN (or TABPFN_API_KEY) is required for cloud inference"
                    )
                from tabpfn_client import TabPFNClassifier, TabPFNRegressor, set_access_token
                from tabpfn_client.models import ClientOptions

                set_access_token(self.access_token)
                options = {"client_options": ClientOptions(timeout=self.timeout_s)}
                clf = TabPFNClassifier.create_default_for_version("v3.5", **options)
                reg = TabPFNRegressor.create_default_for_version("v3.5", **options)
            else:
                from tabpfn import TabPFNClassifier, TabPFNRegressor
                from tabpfn.constants import ModelVersion

                clf = TabPFNClassifier.create_default_for_version(ModelVersion.V3_5)
                reg = TabPFNRegressor.create_default_for_version(ModelVersion.V3_5)
            self._model_classes = (clf.__class__, reg.__class__)
            return self._model_classes
        except DetectorUnavailable:
            raise
        except Exception as exc:
            raise DetectorUnavailable(
                f"TabPFN {self.mode} dependencies/model unavailable ({type(exc).__name__})"
            ) from exc

    def prepare_parallel_inference(self) -> None:
        """Resolve SDK factories before worker threads begin provider operations."""
        self._imports()

    def _new_model(self, kind: str) -> Any:
        classes = self._imports()
        model_class = classes[0 if kind == "classifier" else 1]
        if self.mode == "local":
            from tabpfn.constants import ModelVersion

            return model_class.create_default_for_version(ModelVersion.V3_5)
        from tabpfn_client.models import ClientOptions

        return model_class.create_default_for_version(
            "v3.5", client_options=ClientOptions(timeout=self.timeout_s)
        )

    def _cache_model(self, key: tuple[str, str], model: Any) -> None:
        with self._model_registry_lock:
            if key not in self._models and len(self._models) >= 128:
                self._models.pop(next(iter(self._models)))
            self._models[key] = model

    def _model_lock(self, key: tuple[str, str]) -> Lock:
        return self._model_locks[hash(key) % len(self._model_locks)]

    def _classifier(self, x: np.ndarray, y: np.ndarray) -> Any:
        key = ("classifier", fingerprint(pd.DataFrame(np.column_stack((x, y)))))
        with self._model_lock(key):
            with self._model_registry_lock:
                model = self._models.get(key)
            if model is None:
                model = self._new_model("classifier")
                try:
                    model.fit(x, y)
                except Exception as exc:
                    raise DetectorUnavailable(
                        f"TabPFN classifier fit failed ({type(exc).__name__})"
                    ) from exc
                self._cache_model(key, model)
            return model

    def fit_cause_model(self, features: pd.DataFrame, labels: list[str]) -> str:
        if len(features) != len(labels) or not labels:
            raise ValueError("training feature and label rows must be nonempty and aligned")
        if any(label not in CAUSES for label in labels):
            raise ValueError("training labels contain unsupported causes")
        x, y = _array(features), np.asarray(labels)
        self._classifier(x, y)
        self._cause_features = features.copy()
        self._cause_labels = list(labels)
        return fingerprint(pd.DataFrame(np.column_stack((x, y))))

    def predict_cause(
        self, vector: pd.Series, training_features: pd.DataFrame, training_labels: list[str]
    ) -> tuple[str, float]:
        x_train, y_train = _array(training_features), np.asarray(training_labels)
        model = self._classifier(x_train, y_train)
        aligned = vector.reindex(training_features.columns, fill_value=0.0)
        try:
            probs = model.predict_proba(_array(pd.DataFrame([aligned])))
        except Exception as exc:
            raise DetectorUnavailable(
                f"TabPFN classifier predict failed ({type(exc).__name__})"
            ) from exc
        ix = int(np.argmax(probs[0]))
        return str(model.classes_[ix]), float(probs[0][ix])

    def cause(self, vector: pd.Series) -> tuple[str, float]:
        if self._cause_features is None or self._cause_labels is None:
            raise DetectorUnavailable("cause classifier has not been prepared from TRAIN data")
        return self.predict_cause(vector, self._cause_features, self._cause_labels)

    @staticmethod
    def _predictor_columns(frame: pd.DataFrame) -> list[str]:
        return [
            name
            for name in frame.columns
            if name.endswith(("_lag1", "_mean5", "_std5"))
            or name in {"minute_of_day", "day_of_week"}
        ]

    def forecasts(self, history: pd.DataFrame, horizon: int) -> list[dict[str, Any]]:
        numeric = history.select_dtypes(include=["number"]).tail(2048)
        raw_metrics = [
            name
            for name in numeric.columns
            if name.startswith(RAW_METRIC_PREFIXES) and not name.endswith(DERIVED_SUFFIXES)
        ]
        predictors = self._predictor_columns(numeric)
        if len(numeric) < 8 or not predictors:
            return []
        # Resolve provider classes before worker threads start; several SDKs keep
        # process-global configuration during their first import/factory call.
        self._imports()
        rows: list[dict[str, Any]] = []
        origin = pd.Timestamp(numeric.index.max())
        # Reuse a frozen training context for the current 15-minute bucket.
        training = numeric.loc[numeric.index < origin.floor("15min")]
        if len(training) < 8:
            training = numeric.iloc[:-3]
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FORECASTS) as executor:
            futures = {
                metric: executor.submit(
                    self._forecast_metric,
                    numeric,
                    training,
                    predictors,
                    origin,
                    metric,
                    horizon,
                )
                for metric in raw_metrics
            }
            completed = {}
            try:
                for future in as_completed(
                    futures.values(), timeout=FORECAST_INFERENCE_BUDGET_SECONDS
                ):
                    completed[future] = future.result()
            except TimeoutError as exc:
                for future in futures.values():
                    future.cancel()
                raise DetectorUnavailable(
                    "forecast inference exceeded its "
                    f"{FORECAST_INFERENCE_BUDGET_SECONDS:g}-second wall-time budget"
                ) from exc
            except Exception:
                for future in futures.values():
                    future.cancel()
                raise
            for metric in raw_metrics:
                rows.extend(completed[futures[metric]])
        return rows

    def walk_forward_forecasts(
        self, contexts: Sequence[tuple[pd.DataFrame, pd.Timestamp]]
    ) -> list[list[dict[str, Any]]]:
        """Batch prior-only one-step queries sharing identical TRAIN contexts."""
        if not contexts:
            return []
        self._imports()
        prepared: list[dict[str, Any]] = []
        for history, target_time in contexts:
            numeric = history.select_dtypes(include=["number"]).tail(2048)
            predictors = self._predictor_columns(numeric)
            origin = pd.Timestamp(numeric.index.max())
            training = numeric.loc[numeric.index < origin.floor("15min")]
            if len(training) < 8:
                training = numeric.iloc[:-3]
            query = numeric[predictors].iloc[[-1]].assign(forecast_horizon=1)
            prepared.append(
                {
                    "numeric": numeric,
                    "training": training,
                    "predictors": predictors,
                    "origin": origin,
                    "target_time": pd.Timestamp(target_time),
                    "query": query,
                    "rows": [],
                }
            )

        groups: dict[tuple[str, str], list[tuple[int, pd.DataFrame, np.ndarray]]] = {}
        metrics = [
            name
            for name in prepared[0]["numeric"]
            if name.startswith(RAW_METRIC_PREFIXES) and not name.endswith(DERIVED_SUFFIXES)
        ]
        for context_index, context in enumerate(prepared):
            for metric in metrics:
                train_x, train_y = self._forecast_training(
                    context["training"], context["predictors"], metric
                )
                if len(train_x) < 8 or np.ptp(train_y) <= 1e-12:
                    continue
                key = (
                    f"regressor:{metric}",
                    fingerprint(pd.concat([train_x, pd.Series(train_y)], axis=1)),
                )
                groups.setdefault(key, []).append((context_index, train_x, train_y))

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FORECASTS) as executor:
            futures = {
                executor.submit(
                    self._predict_walk_forward_group,
                    key,
                    group,
                    prepared,
                ): key
                for key, group in groups.items()
            }
            try:
                for future in as_completed(
                    futures, timeout=FORECAST_INFERENCE_BUDGET_SECONDS
                ):
                    future.result()
            except TimeoutError as exc:
                for future in futures:
                    future.cancel()
                raise DetectorUnavailable(
                    "walk-forward forecast batch exceeded its "
                    f"{FORECAST_INFERENCE_BUDGET_SECONDS:g}-second wall-time budget"
                ) from exc
            except Exception:
                for future in futures:
                    future.cancel()
                raise
        for context in prepared:
            context["rows"].sort(key=lambda row: row["metric"])
        return [context["rows"] for context in prepared]

    @staticmethod
    def _forecast_training(
        training: pd.DataFrame, predictors: list[str], metric: str
    ) -> tuple[pd.DataFrame, np.ndarray]:
        x_parts, y_parts = [], []
        for step in range(1, 6):
            x = training[predictors].iloc[:-step].copy()
            x["forecast_horizon"] = step
            y = training[metric].shift(-step).iloc[:-step]
            valid = y.notna()
            x_parts.append(x.loc[valid])
            y_parts.append(y.loc[valid])
        return _bounded_horizon_rows(x_parts, y_parts, MAX_TRAINING_ROWS)

    def _predict_walk_forward_group(
        self,
        key: tuple[str, str],
        group: list[tuple[int, pd.DataFrame, np.ndarray]],
        contexts: list[dict[str, Any]],
    ) -> None:
        metric = key[0].removeprefix("regressor:")
        train_x, train_y = group[0][1], group[0][2]
        with self._model_lock(key):
            with self._model_registry_lock:
                model = self._models.get(key)
            if model is None:
                model = self._new_model("regressor")
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        model.fit(_array(train_x), train_y)
                except Exception as exc:
                    raise DetectorUnavailable(
                        f"TabPFN regressor fit failed ({type(exc).__name__})"
                    ) from exc
                self._cache_model(key, model)
            queries = np.concatenate(
                [_array(contexts[index]["query"]) for index, _, _ in group], axis=0
            )
            try:
                response = model.predict(
                    queries, output_type="quantiles", quantiles=[0.1, 0.5, 0.9]
                )
                predictions = _quantile_matrix(response, len(group))
            except Exception as exc:
                raise DetectorUnavailable(
                    f"TabPFN walk-forward quantile prediction failed ({type(exc).__name__})"
                ) from exc
        for (context_index, _, _), quantiles in zip(group, predictions, strict=True):
            context = contexts[context_index]
            low, median, high = (float(value) for value in quantiles)
            _validate_forecast_values(metric, low, median, high, 1)
            if context["origin"] >= context["target_time"]:
                raise DetectorUnavailable("walk-forward query includes its target observation")
            context["rows"].append(
                {
                    "metric": metric,
                    "made_at": context["origin"].isoformat(),
                    "target_time": context["target_time"].isoformat(),
                    "horizon_minutes": 1,
                    "p10": low,
                    "p50": median,
                    "p90": high,
                    "model": self.provenance,
                }
            )

    def _forecast_metric(
        self,
        numeric: pd.DataFrame,
        training: pd.DataFrame,
        predictors: list[str],
        origin: pd.Timestamp,
        metric: str,
        horizon: int,
    ) -> list[dict[str, Any]]:
        x_parts, y_parts = [], []
        for step in range(1, 6):
            x = training[predictors].iloc[:-step].copy()
            x["forecast_horizon"] = step
            y = training[metric].shift(-step).iloc[:-step]
            valid = y.notna()
            x_parts.append(x.loc[valid])
            y_parts.append(y.loc[valid])
        train_x, train_y = _bounded_horizon_rows(x_parts, y_parts, MAX_TRAINING_ROWS)
        if len(train_x) < 8 or np.ptp(train_y) <= 1e-12:
            return []
        key = (
            f"regressor:{metric}",
            fingerprint(pd.concat([train_x, pd.Series(train_y)], axis=1)),
        )
        with self._model_lock(key):
            with self._model_registry_lock:
                model = self._models.get(key)
            if model is None:
                model = self._new_model("regressor")
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        model.fit(_array(train_x), train_y)
                except Exception as exc:
                    raise DetectorUnavailable(
                        f"TabPFN regressor fit failed ({type(exc).__name__})"
                    ) from exc
                self._cache_model(key, model)
            forecast_x = pd.concat(
                [
                    numeric[predictors].iloc[[-1]].assign(forecast_horizon=step)
                    for step in range(1, horizon + 1)
                ],
                ignore_index=True,
            )
            try:
                response = model.predict(
                    _array(forecast_x), output_type="quantiles", quantiles=[0.1, 0.5, 0.9]
                )
                pred = _quantile_matrix(response, horizon)
            except Exception as exc:
                raise DetectorUnavailable(
                    f"TabPFN quantile prediction failed ({type(exc).__name__})"
                ) from exc
        rows = []
        for offset, quantiles in enumerate(pred, start=1):
            lo, mid, hi = (float(value) for value in quantiles)
            _validate_forecast_values(metric, lo, mid, hi, offset)
            rows.append(
                {
                    "metric": metric,
                    "made_at": origin.isoformat(),
                    "target_time": (
                        origin.floor("min") + pd.Timedelta(minutes=offset)
                    ).isoformat(),
                    "horizon_minutes": offset,
                    "p10": lo,
                    "p50": mid,
                    "p90": hi,
                    "model": self.provenance,
                }
            )
        return rows

    def fit_anomaly(self, normal_training_features: pd.DataFrame) -> None:
        columns = [
            name
            for name in normal_training_features
            if name.startswith(RAW_METRIC_PREFIXES) and not name.endswith(DERIVED_SUFFIXES)
        ]
        data = normal_training_features[columns].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < 5:
            raise DetectorUnavailable(
                "TabPFN anomaly scoring needs at least five normal TRAIN snapshots"
            )
        # The density regressor requires a non-degenerate target support. Constant
        # raw metrics cannot define a continuous density, so omit them using TRAIN
        # observations only; derived/lag features are already excluded above.
        columns = [name for name in columns if data[name].nunique(dropna=True) > 1]
        if not columns:
            raise DetectorUnavailable(
                "TabPFN anomaly scoring needs a varying raw metric in normal TRAIN"
            )
        data = data[columns]
        try:
            self._imports()
            clf, reg = self._new_model("classifier"), self._new_model("regressor")
            module = __import__(
                "tabpfn_extensions.unsupervised", fromlist=["TabPFNUnsupervisedModel"]
            )
            self._unsupervised = module.TabPFNUnsupervisedModel(tabpfn_clf=clf, tabpfn_reg=reg)
            self._unsupervised_module = sys.modules.get(
                module.TabPFNUnsupervisedModel.__module__
            )
            self._unsupervised.fit(_array(data))
            self._anomaly_columns = columns
        except Exception as exc:
            raise DetectorUnavailable(f"TabPFN anomaly fit failed ({type(exc).__name__})") from exc

    def raw_anomaly(self, vector: pd.Series) -> float:
        return self.raw_anomaly_batch([vector])[0]

    def raw_anomaly_batch(self, vectors: Sequence[pd.Series]) -> list[float]:
        """Score aligned snapshots in one extension inference call."""
        if self._unsupervised is None:
            raise DetectorUnavailable(
                "TabPFN anomaly model has not been fit on normal TRAIN snapshots"
            )
        if not vectors:
            return []
        try:
            import torch

            data = np.asarray(
                [
                    vector.reindex(self._anomaly_columns, fill_value=0.0).to_numpy(dtype=float)
                    for vector in vectors
                ],
                dtype=np.float32,
            )
            # The extension uses both its module-level Python RNG for feature ordering
            # and torch's CPU RNG for density noise. Forking preserves the caller's RNG.
            with _ANOMALY_PERMUTATION_LOCK, torch.random.fork_rng(devices=[]):
                torch.manual_seed(ANOMALY_PERMUTATION_SEED)
                if self._unsupervised_module is not None and hasattr(
                    self._unsupervised_module, "random"
                ):
                    previous_random = self._unsupervised_module.random
                    self._unsupervised_module.random = random.Random(
                        ANOMALY_PERMUTATION_SEED
                    )
                    try:
                        result = self._unsupervised.outliers(data, n_permutations=1)
                    finally:
                        self._unsupervised_module.random = previous_random
                else:
                    result = self._unsupervised.outliers(data, n_permutations=1)
            scores = np.asarray(
                result.detach().cpu() if hasattr(result, "detach") else result,
                dtype=float,
            ).reshape(-1)
            if len(scores) != len(vectors) or not np.isfinite(scores).all():
                raise DetectorUnavailable(
                    "TabPFN anomaly scoring returned invalid batch results"
                )
            return scores.tolist()
        except DetectorUnavailable:
            raise
        except Exception as exc:
            raise DetectorUnavailable(
                f"TabPFN anomaly scoring failed ({type(exc).__name__})"
            ) from exc

    def set_anomaly_reference(self, normal_validation_scores: list[float]) -> None:
        values = np.asarray([x for x in normal_validation_scores if np.isfinite(x)], dtype=float)
        if len(values) < 3:
            raise DetectorUnavailable(
                "anomaly calibration needs at least three normal VALIDATION scores"
            )
        self._anomaly_reference = np.sort(values)

    def anomaly(self, vector: pd.Series) -> float:
        if self._anomaly_reference is None:
            raise DetectorUnavailable(
                "anomaly score has not been calibrated on normal VALIDATION cases"
            )
        raw = self.raw_anomaly(vector)
        # Lower log density means more unusual; empirical normal tail probability is stable.
        return float(
            1.0
            - np.searchsorted(self._anomaly_reference, raw, side="right")
            / len(self._anomaly_reference)
        )
