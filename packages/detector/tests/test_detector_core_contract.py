"""Lead-authored public contract mapping and failure cases."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from netcortex_core import DetectionResult, MetricsWindow, ModuleUnavailable

from netcortex_detector import engine


def test_detector_error_is_shared_module_unavailable():
    assert issubclass(engine.DetectorUnavailable, ModuleUnavailable)


def test_detect_rejects_missing_observations():
    window = MetricsWindow(as_of=datetime(2026, 10, 18, tzinfo=UTC))
    with pytest.raises(ModuleUnavailable):
        engine.detect("north-tower", window, window)


def test_result_mapping_preserves_nested_series_and_has_no_db_writes(monkeypatch):
    from netcortex_core import Settings, db

    from netcortex_detector import providers

    at = datetime(2026, 10, 18, 12, tzinfo=UTC)
    times = pd.date_range(at - timedelta(minutes=20), at, freq="30s")
    probes = pd.DataFrame(
        {
            "time": times,
            "site_id": "north-tower",
            "target": "dns:1.1.1.1",
            "kind": "dns",
            "rtt_ms": 30.0,
            "jitter_ms": 2.0,
            "loss_pct": 0.0,
            "source": "sim",
        }
    )
    interfaces = pd.DataFrame(
        {
            "time": times,
            "site_id": "north-tower",
            "iface": "ether1",
            "rx_bps": 100,
            "tx_bps": 100,
            "util_pct": 40.0,
            "drops": 0,
            "errors": 0,
            "source": "sim",
        }
    )
    window = MetricsWindow(as_of=at, probe_metrics=probes, iface_metrics=interfaces)
    monkeypatch.setattr(engine, "Settings", lambda: Settings(_env_file=None), raising=False)

    monkeypatch.setattr(
        providers, "TabPFNBackend", lambda *args, **kwargs: providers.FixtureBackend()
    )

    def forbidden(*args, **kwargs):
        pytest.fail("detect must not persist forecasts")

    monkeypatch.setattr(db, "upsert_forecasts", forbidden)

    def result(*args, **kwargs):
        return {
            "status": "ok",
            "availability": "available",
            "is_anomaly": True,
            "anomaly_score": 0.91,
            "cause": "dns_slow",
            "cause_confidence": 0.8,
            "evidence": ["Measured lookup time increased"],
            "provenance": "fixture: contract test; no model inference",
            "forecasts": [
                {
                    "metric": "rtt_ms_target:dns:1.1.1.1",
                    "horizon_minutes": h,
                    "made_at": at.isoformat(),
                    "target_time": (at + timedelta(minutes=h)).isoformat(),
                    "p10": 20.0,
                    "p50": 30.0,
                    "p90": 40.0,
                }
                for h in range(1, 6)
            ],
        }

    real_engine = engine.run_engine
    monkeypatch.setattr(engine, "run_engine", result)
    detection = engine.detect("north-tower", window, window)
    assert isinstance(detection, DetectionResult)
    assert detection.score == 0.91 and detection.cause_guess.value == "dns_slow"
    assert detection.mode == "mock"
    assert detection.series[0].series_key == "probe:dns:1.1.1.1:rtt_ms"
    assert [p.time for p in detection.series[0].points] == [
        at + timedelta(minutes=h) for h in range(1, 6)
    ]

    # Exercise the feature builder too: canonical keys must survive actual engine names.
    monkeypatch.setattr(engine, "run_engine", real_engine)
    actual = engine.detect("north-tower", window, window)
    keys = {item.series_key for item in actual.series}
    assert "probe:dns:1.1.1.1:rtt_ms" in keys
    assert "iface:ether1:util_pct" in keys
    assert all(len(item.points) == 5 for item in actual.series)
