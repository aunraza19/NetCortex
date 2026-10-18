"""Lead Gate 2 acceptance cases: provider-free tests are not a live pass."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from netcortex_core import DetectionResult, MetricsWindow, ModuleUnavailable, Settings

from netcortex_detector import engine, providers


def _write_case(root: Path, split: str, number: int, cause: str) -> None:
    folder = root / split
    folder.mkdir(parents=True, exist_ok=True)
    offset = number + (100 if split == "validation" else 0)
    start = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=offset)
    times = pd.date_range(start, periods=40, freq="min")
    probes = pd.DataFrame(
        {
            "time": times,
            "site_id": "north-tower",
            "target": "1.1.1.1",
            "kind": "icmp",
            "rtt_ms": [10.0 + i % 5 for i in range(40)],
            "jitter_ms": 1.0,
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
            "util_pct": [30.0 + i % 7 for i in range(40)],
            "drops": 0,
            "errors": 0,
            "source": "sim",
        }
    )
    prefix = f"{split}-{number}"
    probes.to_parquet(folder / f"{prefix}-probe.parquet", index=False)
    interfaces.to_parquet(folder / f"{prefix}-iface.parquet", index=False)
    case = {
        "case_id": prefix,
        "split": split,
        "seed": offset,
        "site_id": "north-tower",
        "case_start": start.isoformat(),
        "as_of": times[-1].isoformat(),
        "history_window": {"start": start.isoformat(), "end_exclusive": times[9].isoformat()},
        "detection_window": {"start": times[9].isoformat(), "end_inclusive": times[-1].isoformat()},
        "expected": {"cause": cause, "template_id": "none", "params": {}},
        "observations": {"probe": f"{prefix}-probe.parquet", "iface": f"{prefix}-iface.parquet"},
    }
    (folder / f"{prefix}.json").write_text(json.dumps(case), encoding="utf-8")


@pytest.fixture
def training_cases(tmp_path):
    causes = ["normal"] * 5 + ["dns_slow", "heavy_user", "uplink_down"]
    for number, cause in enumerate(causes):
        _write_case(tmp_path, "train", number, cause)
    for number in range(3):
        _write_case(tmp_path, "validation", number, "normal")
    (tmp_path / "test").mkdir()
    # Any attempt to parse test metadata would fail; preparation must ignore it.
    (tmp_path / "test" / "never-read.json").write_text("DO NOT READ TEST", encoding="utf-8")
    return tmp_path


def test_preparation_ignores_test_and_rejects_invalid_artifact(training_cases, tmp_path):
    from netcortex_detector.preparation import configure_detector, prepare_detector

    artifact = prepare_detector(training_cases, tmp_path / "training.json")
    assert artifact.is_file()
    payload = artifact.read_text()
    assert "DO NOT READ TEST" not in payload
    assert "tabpfn_token" not in payload.lower()
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(ModuleUnavailable):
        configure_detector(bad, settings=Settings(_env_file=None))


def test_prepared_backend_is_used_by_public_detect(training_cases, tmp_path, monkeypatch):
    from netcortex_detector.preparation import (
        clear_prepared_detector,
        configure_detector,
        prepare_detector,
    )

    class Backend(providers.FixtureBackend):
        provenance = "tabpfn-cloud:v3.5"
        mode = "cloud"

        def __init__(self):
            self.fit_calls = 0
            self.raw_calls = 0

        def fit_cause_model(self, features, labels):
            self.fit_calls += 1
            assert len(labels) == 8 and set(labels) == {
                "normal",
                "dns_slow",
                "heavy_user",
                "uplink_down",
            }

        def fit_anomaly(self, features):
            assert len(features) == 5

        def raw_anomaly(self, vector):
            self.raw_calls += 1
            return -float(vector.iloc[0])

        def set_anomaly_reference(self, scores):
            assert len(scores) == 3

        def predict_cause(self, vector, features, labels):
            return "dns_slow", 0.9

        def cause(self, vector):
            return "dns_slow", 0.9

        def anomaly(self, vector):
            return 0.8

    backend = Backend()
    settings = Settings(_env_file=None, tabpfn_mode="cloud")
    artifact = prepare_detector(training_cases, tmp_path / "training.json")
    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    try:
        configure_detector(artifact, settings=settings, backend_factory=lambda *a, **k: backend)
        folder = training_cases / "validation"
        window = MetricsWindow(
            as_of=datetime(2025, 4, 11, 0, 39, tzinfo=UTC),
            probe_metrics=pd.read_parquet(folder / "validation-0-probe.parquet"),
            iface_metrics=pd.read_parquet(folder / "validation-0-iface.parquet"),
        )
        first = engine.detect("north-tower", window, window)
        second = engine.detect("north-tower", window, window)
        assert isinstance(first, DetectionResult) and isinstance(second, DetectionResult)
        assert first.mode == "cloud" and first.model.startswith("tabpfn-")
        assert first.series and all(len(s.points) == 5 for s in first.series)
        assert backend.fit_calls == 1 and backend.raw_calls == 3
    finally:
        clear_prepared_detector()


def test_rotating_runtime_configuration_rebuilds_cached_backend(training_cases, tmp_path):
    from netcortex_detector.preparation import (
        clear_prepared_detector,
        configure_detector,
        prepare_detector,
    )

    created = []

    class Backend:
        provenance = "tabpfn-cloud:v3.5"

        def __init__(self, mode, *, access_token, timeout_s):
            self.mode = mode
            created.append((access_token, timeout_s))

        def fit_cause_model(self, features, labels):
            pass

        def fit_anomaly(self, features):
            pass

        def raw_anomaly(self, vector):
            return -1.0

        def set_anomaly_reference(self, scores):
            pass

    def settings(token, timeout):
        return Settings(_env_file=None, TABPFN_TOKEN=token, http_timeout_s=timeout)

    artifact = prepare_detector(training_cases, tmp_path / "training.json")
    clear_prepared_detector()
    try:
        first = configure_detector(
            artifact, settings=settings("dummy-a", 10), backend_factory=Backend
        )
        assert (
            configure_detector(artifact, settings=settings("dummy-a", 10), backend_factory=Backend)
            is first
        )
        rotated = configure_detector(
            artifact, settings=settings("dummy-b", 10), backend_factory=Backend
        )
        assert rotated is not first
        changed_timeout = configure_detector(
            artifact, settings=settings("dummy-b", 20), backend_factory=Backend
        )
        assert changed_timeout is not rotated
        assert created == [("dummy-a", 10), ("dummy-b", 10), ("dummy-b", 20)]
    finally:
        clear_prepared_detector()
