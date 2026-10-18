from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from netcortex_detector.engine import (
    DetectorConfig,
    DetectorUnavailable,
    build_features,
    detect,
    fingerprint,
    run_engine,
)
from netcortex_detector.providers import FixtureBackend, TabPFNBackend


def frames(site: str = "s1", *, minutes: int = 12, start: datetime | None = None):
    start = start or datetime(2026, 1, 1, tzinfo=UTC)
    times = pd.date_range(start, periods=minutes * 6, freq="10s")
    p = pd.DataFrame(
        {
            "time": times,
            "site_id": site,
            "target": "internet",
            "rtt_ms": 30.0,
            "jitter_ms": 1.0,
            "loss_pct": 0.0,
            "source": "sim",
        }
    )
    it = pd.date_range(start, periods=minutes * 2, freq="30s")
    i = pd.DataFrame(
        {
            "time": it,
            "site_id": site,
            "iface": "wan",
            "util_pct": 40.0,
            "drops": 0,
            "errors": 0,
            "source": "sim",
        }
    )
    return p, i


def test_future_observations_cannot_change_features_at_cutoff():
    p, i = frames()
    cutoff = p.time.iloc[-1]
    baseline = build_features(p, i, site_id="s1", as_of=cutoff)
    changed_p = p.copy()
    changed_p.loc[changed_p.time > cutoff, "rtt_ms"] = 9000
    changed_i = i.copy()
    changed_i.loc[changed_i.time > cutoff, "util_pct"] = 99
    changed = build_features(changed_p, changed_i, site_id="s1", as_of=cutoff)
    pd.testing.assert_frame_equal(baseline, changed)


def test_site_isolation_rejects_mixed_site_rows():
    p, i = frames()
    p.loc[0, "site_id"] = "other"
    with pytest.raises(ValueError, match="different site"):
        build_features(p, i, site_id="s1", as_of=p.time.max())


def test_mixed_measurement_sources_are_rejected_within_and_across_frames():
    p, i = frames()
    p.loc[0, "source"] = "live"
    with pytest.raises(ValueError, match="mixes measurement sources"):
        build_features(p, i, site_id="s1", as_of=p.time.max())
    p, i = frames()
    i["source"] = "live"
    with pytest.raises(ValueError, match="different measurement source"):
        build_features(p, i, site_id="s1", as_of=p.time.max())


def test_supplemental_rows_are_not_core_probe_inputs():
    p, i = frames()
    p["source"] = "sim_supplemental"
    with pytest.raises(ValueError, match="supplemental"):
        build_features(p, i, site_id="s1", as_of=p.time.max())


def test_quantile_bands_are_ordered_and_scores_bounded():
    p, i = frames()
    result = run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=FixtureBackend())
    assert result["status"] == "ok"
    assert 0 <= result["anomaly_score"] <= 1
    assert all(row["p10"] <= row["p50"] <= row["p90"] for row in result["forecasts"])


def test_sparse_history_is_explicitly_not_healthy():
    p, i = frames(minutes=3)
    result = run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=FixtureBackend())
    assert result["status"] == "insufficient_history"
    assert result["is_anomaly"] is None
    assert result["cause"] is None


def test_invalid_metric_ranges_are_rejected():
    p, i = frames()
    i.loc[0, "util_pct"] = 101
    with pytest.raises(ValueError, match="valid range"):
        build_features(p, i, site_id="s1", as_of=p.time.max())


def test_stale_and_missing_data_are_unavailable_not_healthy():
    p, i = frames()
    cutoff = p.time.max() + pd.Timedelta(minutes=5)
    stale = run_engine(p, i, site_id="s1", as_of=cutoff, backend=FixtureBackend())
    assert stale["status"] == "stale_data"
    assert stale["is_anomaly"] is None
    missing = run_engine(p.iloc[:0], i, site_id="s1", as_of=p.time.max(), backend=FixtureBackend())
    assert missing["status"] == "missing_probe_data"
    assert missing["is_anomaly"] is None


def test_future_probe_rows_do_not_make_stale_past_probe_data_look_fresh():
    p, i = frames()
    cutoff = p.time.max() + pd.Timedelta(minutes=3)
    future = p.iloc[[-1]].copy()
    future["time"] = cutoff + pd.Timedelta(minutes=1)
    p = pd.concat([p, future], ignore_index=True)
    i.loc[len(i)] = [cutoff, "s1", "wan", 40.0, 0, 0, "sim"]
    result = run_engine(p, i, site_id="s1", as_of=cutoff, backend=FixtureBackend())
    assert result["status"] == "stale_data"
    assert result["is_anomaly"] is None


def test_total_loss_allows_missing_rtt_but_all_missing_probe_metrics_are_unavailable():
    p, i = frames()
    p["rtt_ms"] = np.nan
    p["loss_pct"] = 100.0
    total_loss = run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=FixtureBackend())
    assert total_loss["status"] == "ok"
    p["loss_pct"] = np.nan
    missing = run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=FixtureBackend())
    assert missing["status"] == "invalid_measurements"
    assert missing["is_anomaly"] is None


def test_provider_failure_is_explicit():
    class Broken(FixtureBackend):
        def forecasts(self, history, horizon):
            raise TimeoutError("offline")

    p, i = frames()
    with pytest.raises(DetectorUnavailable, match="inference failed"):
        run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=Broken())


@pytest.mark.parametrize(
    "forecast_row",
    [
        {"metric": "rtt_ms_internet", "horizon_minutes": 1, "p10": np.nan, "p50": 2, "p90": 3},
        {"metric": "rtt_ms_internet", "horizon_minutes": 1, "p10": 3, "p50": 2, "p90": 4},
        {"metric": "loss_pct_internet", "horizon_minutes": 1, "p10": 0, "p50": 50, "p90": 101},
        {"metric": "rtt_ms_internet", "horizon_minutes": 6, "p10": 1, "p50": 2, "p90": 3},
        {"metric": "unknown_metric", "horizon_minutes": 1, "p10": 1, "p50": 2, "p90": 3},
    ],
)
def test_invalid_forecast_outputs_fail_explicitly(forecast_row):
    class InvalidForecast(FixtureBackend):
        def forecasts(self, history, horizon):
            return [forecast_row]

    p, i = frames()
    with pytest.raises(DetectorUnavailable, match="inference failed"):
        run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=InvalidForecast())


def test_no_tabpfn_key_or_dependency_never_silently_uses_fixture():
    backend = TabPFNBackend("cloud", access_token=None)
    p, i = frames()
    with pytest.raises(DetectorUnavailable):
        run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=backend)


def test_context_fingerprint_changes_when_training_context_changes():
    p, _ = frames()
    first = fingerprint(p)
    changed = p.copy()
    changed.loc[0, "rtt_ms"] = 31
    assert fingerprint(changed) != first


def test_context_truncated_to_configured_limit():
    p, i = frames(minutes=15)

    class Capture(FixtureBackend):
        seen = 0

        def forecasts(self, history, horizon):
            self.seen = len(history)
            return super().forecasts(history, horizon)

    backend = Capture()
    run_engine(
        p,
        i,
        site_id="s1",
        as_of=p.time.max(),
        backend=backend,
        config=DetectorConfig(context_rows=7),
    )
    assert backend.seen <= 7


def test_public_core_adapter_rejects_non_core_windows():
    with pytest.raises(DetectorUnavailable, match="MetricsWindow"):
        detect("s1", object(), object())


def test_public_detect_requires_real_startup_setup_before_provider_calls(monkeypatch):
    from netcortex_core import MetricsWindow, Settings

    from netcortex_detector import engine, providers
    from netcortex_detector.preparation import clear_prepared_detector

    probes, interfaces = frames(minutes=6)
    probes["kind"] = "icmp"
    interfaces["rx_bps"] = 100
    interfaces["tx_bps"] = 100
    window = MetricsWindow(
        as_of=probes.time.max().to_pydatetime(),
        probe_metrics=probes,
        iface_metrics=interfaces,
    )

    class UnpreparedRealBackend:
        provenance = "tabpfn-cloud:v3.5"
        mode = "cloud"

        def forecasts(self, history, horizon):
            pytest.fail("detect must reject an unprepared backend before provider calls")

    monkeypatch.setattr(engine, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(providers, "TabPFNBackend", lambda *args, **kwargs: UnpreparedRealBackend())
    clear_prepared_detector()
    try:
        with pytest.raises(DetectorUnavailable, match="configure_detector"):
            detect("s1", window, window)
    finally:
        clear_prepared_detector()


def test_forecast_compare_only_uses_prior_forecast_samples():
    from netcortex_detector.engine import consecutive_forecast_exceedances

    observed = pd.Series(
        [4.0, 5.0, 6.0], index=pd.date_range("2026-01-01", periods=3, freq="min", tz="UTC")
    )
    made_at = observed.index - pd.Timedelta(minutes=1)
    forecasts = pd.DataFrame(
        {"made_at": made_at, "target_time": observed.index, "p90": [3.0, 4.0, 5.0]}
    )
    assert consecutive_forecast_exceedances(observed, forecasts) == 3
    future_forecast = pd.DataFrame(
        {
            "made_at": [observed.index[-1] + pd.Timedelta(minutes=1)],
            "target_time": [observed.index[-1]],
            "p90": [0.0],
        }
    )
    assert consecutive_forecast_exceedances(observed, future_forecast) == 0


def test_walk_forward_sustained_rule_rejects_gapped_minutes():
    from netcortex_detector.engine import (
        DetectorConfig,
        _walk_forward_exceedances,
        build_features,
    )

    class FixedForecast(FixtureBackend):
        def forecasts(self, history, horizon):
            origin = pd.Timestamp(history.index.max())
            return [
                {
                    "metric": metric,
                    "made_at": origin.isoformat(),
                    "target_time": (origin + pd.Timedelta(minutes=1)).isoformat(),
                    "horizon_minutes": 1,
                    "p90": 1.0,
                }
                for metric in history.columns
                if metric.startswith(("rtt_ms_", "loss_pct_", "iface_util_pct_"))
            ]

    p, i = frames(minutes=10)
    features = build_features(p, i, site_id="s1", as_of=p.time.max())
    features = features.drop(features.index[-2])
    features.iloc[-3:, features.columns.get_loc("rtt_ms_target:internet")] = 99.0
    assert not _walk_forward_exceedances(features, FixedForecast(), DetectorConfig())


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_nonfinite_anomaly_scores_are_unavailable(bad_value):
    class BadScore(FixtureBackend):
        def anomaly(self, vector):
            return bad_value

    p, i = frames()
    with pytest.raises(DetectorUnavailable, match="inference failed"):
        run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=BadScore())


@pytest.mark.parametrize("bad_confidence", [np.nan, np.inf, -np.inf])
def test_nonfinite_cause_confidence_is_unavailable(bad_confidence):
    class BadConfidence(FixtureBackend):
        def cause(self, vector):
            return "normal", bad_confidence

    p, i = frames()
    with pytest.raises(DetectorUnavailable, match="inference failed"):
        run_engine(p, i, site_id="s1", as_of=p.time.max(), backend=BadConfidence())


def test_one_spike_does_not_count_as_a_sustained_event():
    from netcortex_detector.engine import consecutive_forecast_exceedances

    at = pd.date_range("2026-01-01", periods=5, freq="min", tz="UTC")
    observed = pd.Series([1.0, 1.0, 1.0, 1.0, 5.0], index=at)
    forecasts = pd.DataFrame(
        {
            "made_at": at - pd.Timedelta(minutes=1),
            "target_time": at,
            "p90": [2.0] * 5,
        }
    )
    assert consecutive_forecast_exceedances(observed, forecasts) == 0


def test_walk_forward_rule_needs_three_actual_exceedances():
    from netcortex_detector.engine import DetectorConfig, run_engine
    from netcortex_detector.providers import FixtureBackend

    class FixedForecast(FixtureBackend):
        def forecasts(self, history, horizon):
            origin = pd.Timestamp(history.index.max())
            return [
                {
                    "metric": metric,
                    "made_at": origin.isoformat(),
                    "target_time": (origin.floor("min") + pd.Timedelta(minutes=step)).isoformat(),
                    "horizon_minutes": step,
                    "p10": 10.0,
                    "p50": 20.0,
                    "p90": 40.0,
                }
                for metric in history.columns
                if metric.startswith(("rtt_ms_", "loss_pct_", "iface_util_pct_"))
                for step in range(1, horizon + 1)
            ]

        def anomaly(self, vector):
            return 0.0

    p, i = frames(minutes=12)
    last_three = p.time.max().floor("min") - pd.Timedelta(minutes=2)
    single = p.copy()
    single.loc[single.time >= p.time.max().floor("min"), "rtt_ms"] = 1000.0
    one = run_engine(
        single,
        i,
        site_id="s1",
        as_of=p.time.max(),
        backend=FixedForecast(),
        config=DetectorConfig(threshold=0.9),
        anomaly_threshold=0.9,
    )
    assert one["sustained_forecast_exceedance"] is False
    persistent = p.copy()
    persistent.loc[persistent.time.dt.floor("min") >= last_three, "rtt_ms"] = 1000.0
    three = run_engine(
        persistent,
        i,
        site_id="s1",
        as_of=p.time.max(),
        backend=FixedForecast(),
        config=DetectorConfig(threshold=0.9),
        anomaly_threshold=0.9,
    )
    assert three["sustained_forecast_exceedance"] is True


def test_tabpfn_adapter_fits_lagged_forecasts_and_joint_quantiles(monkeypatch):
    from contextlib import nullcontext
    from threading import Lock
    from time import sleep

    from netcortex_detector.providers import TabPFNBackend

    calls = {"reg_fit": 0, "predict": 0, "clf_fit": 0, "unsup_fit": 0, "outliers": 0}
    regression_fit_rows = []
    concurrency = {"active": 0, "max_active": 0}
    concurrency_lock = Lock()

    class FakeRegressor:
        def fit(self, x, y):
            with concurrency_lock:
                calls["reg_fit"] += 1
                concurrency["active"] += 1
                concurrency["max_active"] = max(
                    concurrency["max_active"], concurrency["active"]
                )
            assert x.shape[1] > 1
            regression_fit_rows.append(x.copy())
            self.columns = x.shape[1]
            sleep(0.02)
            with concurrency_lock:
                concurrency["active"] -= 1

        def predict(self, x, *, output_type, quantiles):
            calls["predict"] += 1
            assert output_type == "quantiles"
            assert quantiles == [0.1, 0.5, 0.9]
            horizons = x[:, -1].astype(int)
            return [10 + horizons, 20 + horizons, 30 + horizons]

    class FakeClassifier:
        classes_ = np.array(["normal", "uplink_congestion"])

        def fit(self, x, y):
            calls["clf_fit"] += 1

        def predict_proba(self, x):
            return np.tile(np.array([[0.2, 0.8]]), (len(x), 1))

    class FakeUnsupervised:
        def __init__(self, *, tabpfn_clf, tabpfn_reg):
            assert tabpfn_clf is not None and tabpfn_reg is not None

        def fit(self, x):
            calls["unsup_fit"] += 1
            self.width = x.shape[1]

        def outliers(self, x, *, n_permutations):
            assert n_permutations == 1
            calls["outliers"] += 1
            return np.linspace(-1.0, -2.0, len(x))

    class Backend(TabPFNBackend):
        def _imports(self):
            return FakeClassifier, FakeRegressor

        def _new_model(self, kind):
            return FakeClassifier() if kind == "classifier" else FakeRegressor()

    extension = ModuleType("tabpfn_extensions.unsupervised")
    extension.TabPFNUnsupervisedModel = FakeUnsupervised
    package = ModuleType("tabpfn_extensions")
    package.__path__ = []
    monkeypatch.setitem(__import__("sys").modules, "tabpfn_extensions", package)
    monkeypatch.setitem(__import__("sys").modules, "tabpfn_extensions.unsupervised", extension)
    seeded_values = []
    fake_torch = SimpleNamespace(
        manual_seed=seeded_values.append,
        random=SimpleNamespace(
            fork_rng=lambda *, devices: nullcontext(),
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    backend = Backend("local")
    p, i = frames(minutes=20)
    p["rtt_ms"] = 30.0 + np.arange(len(p)) * 0.1
    i["util_pct"] = 40.0 + np.arange(len(i)) * 0.2
    features = build_features(p, i, site_id="s1", as_of=p.time.max())
    forecast = backend.forecasts(features, 5)
    assert forecast
    assert concurrency["max_active"] <= 8
    assert all(row["p10"] <= row["p50"] <= row["p90"] for row in forecast)
    by_horizon = {
        row["horizon_minutes"]: row for row in forecast if row["metric"].startswith("rtt_ms_")
    }
    assert [by_horizon[h]["p10"] for h in range(1, 6)] == [11, 12, 13, 14, 15]
    assert [by_horizon[h]["p50"] for h in range(1, 6)] == [21, 22, 23, 24, 25]
    assert [by_horizon[h]["p90"] for h in range(1, 6)] == [31, 32, 33, 34, 35]
    assert all(not row["metric"].endswith(("_lag1", "_mean5", "_std5")) for row in forecast)
    assert calls["predict"] == len(forecast) // 5
    backend.forecasts(features, 5)
    assert calls["reg_fit"] == len(forecast) // 5

    training = pd.DataFrame([features.iloc[-1], features.iloc[-2]])
    assert backend.fit_cause_model(training, ["normal", "uplink_congestion"])
    assert (
        backend.predict_cause(features.iloc[-1], training, ["normal", "uplink_congestion"])[0]
        == "uplink_congestion"
    )
    normal = pd.DataFrame([features.iloc[index] for index in range(10)])
    normal["rtt_ms_constant"] = 42.0
    backend.fit_anomaly(normal)
    assert calls["unsup_fit"] == 1
    assert "rtt_ms_constant" not in backend._anomaly_columns
    assert all(normal[column].nunique() > 1 for column in backend._anomaly_columns)
    reference = backend.raw_anomaly_batch([normal.iloc[index] for index in range(3)])
    assert reference == [-1.0, -1.5, -2.0]
    assert calls["outliers"] == 1
    backend.set_anomaly_reference(reference)
    assert 0.0 <= backend.anomaly(features.iloc[-1]) <= 1.0
    assert seeded_values == [73021] * 2

    large_p, large_i = frames(minutes=600)
    large = build_features(large_p, large_i, site_id="s1", as_of=large_p.time.max())
    backend.forecasts(large, 5)
    latest_fit = regression_fit_rows[-1]
    assert len(latest_fit) <= 2048
    assert set(latest_fit[:, -1].astype(int)) == {1, 2, 3, 4, 5}


def test_forecast_processes_all_twelve_metrics_with_bounded_parallelism(monkeypatch):
    from threading import Lock
    from time import sleep

    from netcortex_detector.providers import MAX_PARALLEL_FORECASTS, TabPFNBackend

    active = 0
    peak = 0
    guard = Lock()
    fitted = []

    class FakeModel:
        def fit(self, x, y):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            sleep(0.01)
            fitted.append(len(y))
            with guard:
                active -= 1

        def predict(self, x, *, output_type, quantiles):
            assert output_type == "quantiles" and quantiles == [0.1, 0.5, 0.9]
            values = np.ones(len(x), dtype=float)
            return [values, values * 2, values * 3]

    backend = TabPFNBackend("local")
    monkeypatch.setattr(backend, "_imports", lambda: (FakeModel, FakeModel))
    monkeypatch.setattr(backend, "_new_model", lambda _kind: FakeModel())
    history = pd.DataFrame(
        {
            "minute_of_day": np.arange(20, dtype=float),
            **{
                f"rtt_ms_target:{position}": np.arange(20, dtype=float) + position
                for position in range(12)
            },
        },
        index=pd.date_range("2026-01-01", periods=20, freq="min", tz="UTC"),
    )

    forecasts = backend.forecasts(history, 5)

    assert len(forecasts) == 12 * 5
    assert {row["metric"] for row in forecasts} == {
        f"rtt_ms_target:{position}" for position in range(12)
    }
    assert len(fitted) == 12
    assert 2 <= peak <= MAX_PARALLEL_FORECASTS
    assert len(backend._model_locks) == 64


def test_forecast_walltime_budget_cancels_queued_metric_work(monkeypatch):
    from time import sleep

    from netcortex_detector import providers

    monkeypatch.setattr(providers, "FORECAST_INFERENCE_BUDGET_SECONDS", 0.005)
    backend = providers.TabPFNBackend("local")
    monkeypatch.setattr(backend, "_imports", lambda: (object, object))
    started = []

    def slow_forecast(_numeric, _training, _predictors, _origin, metric, _horizon):
        started.append(metric)
        sleep(0.05)
        return []

    monkeypatch.setattr(backend, "_forecast_metric", slow_forecast)
    history = pd.DataFrame(
        {
            "minute_of_day": np.arange(20, dtype=float),
            **{
                f"rtt_ms_target:{position}": np.arange(20, dtype=float) + position
                for position in range(12)
            },
        },
        index=pd.date_range("2026-01-01", periods=20, freq="min", tz="UTC"),
    )

    with pytest.raises(DetectorUnavailable, match="wall-time budget"):
        backend.forecasts(history, 5)
    assert len(started) < 12


def test_tabpfn_walk_forward_batch_matches_sequential_across_bucket(monkeypatch):
    from netcortex_detector.providers import TabPFNBackend

    predicted_batches = []

    class FakeModel:
        def fit(self, _x, _y):
            pass

        def predict(self, x, *, output_type, quantiles):
            assert output_type == "quantiles" and quantiles == [0.1, 0.5, 0.9]
            predicted_batches.append(len(x))
            medians = x[:, 0]
            return [medians - 1, medians, medians + 1]

    backend = TabPFNBackend("local")
    monkeypatch.setattr(backend, "_imports", lambda: (FakeModel, FakeModel))
    monkeypatch.setattr(backend, "_new_model", lambda _kind: FakeModel())
    times = pd.date_range("2026-01-01 14:00", periods=100, freq="min", tz="UTC")
    features = pd.DataFrame(
        {
            "minute_of_day": np.arange(100, dtype=float),
            "rtt_ms_target:one": np.arange(100, dtype=float) + 20,
            "rtt_ms_target:one_lag1": np.arange(100, dtype=float) + 19,
        },
        index=times,
    )
    target_times = [
        pd.Timestamp("2026-01-01 15:00", tz="UTC"),
        pd.Timestamp("2026-01-01 15:01", tz="UTC"),
        pd.Timestamp("2026-01-01 15:02", tz="UTC"),
    ]
    contexts = [
        (features.loc[features.index < target].tail(80), target) for target in target_times
    ]
    sequential = [backend.forecasts(history, 1) for history, _ in contexts]
    predicted_batches.clear()

    batched = backend.walk_forward_forecasts(contexts)

    assert batched == sequential
    assert sorted(predicted_batches) == [1, 2]
    for (history, target), result in zip(contexts, batched, strict=True):
        assert all(pd.Timestamp(row["made_at"]) < target for row in result)
        assert all(pd.Timestamp(row["target_time"]) == target for row in result)
        assert history.index.max() < target


def test_tabpfn_walk_forward_batch_fails_closed_on_group_error(monkeypatch):
    from netcortex_detector.providers import TabPFNBackend

    class BrokenModel:
        def fit(self, _x, _y):
            pass

        def predict(self, _x, *, output_type, quantiles):
            raise RuntimeError("synthetic provider failure")

    backend = TabPFNBackend("local")
    monkeypatch.setattr(backend, "_imports", lambda: (BrokenModel, BrokenModel))
    monkeypatch.setattr(backend, "_new_model", lambda _kind: BrokenModel())
    times = pd.date_range("2026-01-01", periods=40, freq="min", tz="UTC")
    features = pd.DataFrame(
        {
            "minute_of_day": np.arange(40, dtype=float),
            "rtt_ms_target:one": np.arange(40, dtype=float) + 20,
            "rtt_ms_target:one_lag1": np.arange(40, dtype=float) + 19,
        },
        index=times,
    )
    target = times[-1] + pd.Timedelta(minutes=1)
    history = features.loc[features.index < target].tail(30)

    with pytest.raises(DetectorUnavailable, match="walk-forward quantile prediction failed"):
        backend.walk_forward_forecasts([(history, target)])


def test_cloud_adapter_pins_timeout_and_version_without_logging_token(monkeypatch):
    from netcortex_detector.providers import TabPFNBackend

    records = {}

    class Model:
        @classmethod
        def create_default_for_version(cls, version, **kwargs):
            records[cls.__name__] = (version, kwargs)
            return cls()

    class Classifier(Model):
        pass

    class Regressor(Model):
        pass

    client = ModuleType("tabpfn_client")
    client.TabPFNClassifier = Classifier
    client.TabPFNRegressor = Regressor
    client.set_access_token = lambda token: records.update(token_set=token)
    models = ModuleType("tabpfn_client.models")
    models.ClientOptions = lambda *, timeout: SimpleNamespace(timeout=timeout)
    monkeypatch.setitem(sys.modules, "tabpfn_client", client)
    monkeypatch.setitem(sys.modules, "tabpfn_client.models", models)

    backend = TabPFNBackend("cloud", access_token="secret-token", timeout_s=7.0)
    backend._imports()
    assert records["token_set"] == "secret-token"
    assert records["Classifier"] == ("v3.5", {"client_options": SimpleNamespace(timeout=7.0)})
    assert records["Regressor"] == ("v3.5", {"client_options": SimpleNamespace(timeout=7.0)})


def test_eval_threshold_uses_validation_labels_and_false_alert_budget():
    from netcortex_detector.thresholds import calibrate_threshold, normal_site_days

    threshold = calibrate_threshold([0.05, 0.4, 0.8], [False, True, True], ["s1", "s1", "s1"])
    assert threshold == 0.05

    normal_exposure = [("s1", "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z")]
    site_days = normal_site_days(normal_exposure)
    base_threshold = calibrate_threshold([0.8], [False], ["s1"], exposure_intervals=normal_exposure)
    expanded_threshold = calibrate_threshold(
        [0.8, 0.7, 0.9],
        [False, True, True],
        ["s1"] * 3,
        exposure_intervals=normal_exposure,
    )
    assert site_days == 0.5 / 24
    assert expanded_threshold == base_threshold == 0.8
    assert not any(score > expanded_threshold for score in [0.8])
    assert (
        normal_site_days([*normal_exposure, ("s1", "2026-01-01T00:15:00Z", "2026-01-01T00:45:00Z")])
        == 0.75 / 24
    )


def test_eval_rejects_overlapping_splits_and_path_escape(tmp_path):
    runner_path = Path(__file__).resolve().parents[3] / "eval" / "run.py"
    runner = run_path(str(runner_path))

    def make_case(split, case_id, seed, start, end):
        return {
            "split": split,
            "case_id": case_id,
            "seed": seed,
            "case_start": start,
            "as_of": end,
        }

    train = [make_case("train", "a", 1, "2026-01-01T00:00:00Z", "2026-01-01T03:00:00Z")]
    validation = [make_case("validation", "b", 2, "2026-01-01T02:00:00Z", "2026-01-01T05:00:00Z")]
    test = [make_case("test", "c", 3, "2026-01-03T00:00:00Z", "2026-01-03T03:00:00Z")]
    with pytest.raises(ValueError, match="time windows overlap"):
        runner["_verify_splits"](train, validation, test)

    split = tmp_path / "test"
    split.mkdir()
    sidecar = split / "case.json"
    sidecar.write_text(
        '{"observations":{"probe":"../escape.parquet","iface":"iface.parquet"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="escapes"):
        runner["_load_case"](sidecar)
