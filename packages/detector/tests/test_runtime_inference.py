"""Lead acceptance: overlap independent calls without changing causal evidence."""

from datetime import UTC, datetime
from threading import Barrier, Lock

import pandas as pd
import pytest

from netcortex_detector.engine import DetectorUnavailable, run_engine
from netcortex_detector.providers import FixtureBackend


def observations():
    times = pd.date_range(datetime(2026, 1, 1, tzinfo=UTC), periods=90, freq="10s")
    probes = pd.DataFrame(
        {
            "time": times,
            "site_id": "test",
            "target": "1.1.1.1",
            "rtt_ms": 30.0,
            "jitter_ms": 1.0,
            "loss_pct": 0.0,
            "source": "sim",
        }
    )
    interfaces = pd.DataFrame(
        {
            "time": times,
            "site_id": "test",
            "iface": "ether1",
            "util_pct": 40.0,
            "drops": 0,
            "errors": 0,
            "source": "sim",
        }
    )
    return probes, interfaces


def test_independent_real_backend_calls_overlap_and_keep_identical_output():
    probes, interfaces = observations()
    expected = run_engine(
        probes, interfaces, site_id="test", as_of=probes.time.max(), backend=FixtureBackend()
    )
    entered = []
    guard = Lock()
    barrier = Barrier(4, timeout=3)

    class ConcurrentBackend(FixtureBackend):
        supports_parallel_inference = True

        def enter(self, name):
            with guard:
                first = name not in entered
                if first:
                    entered.append(name)
            if first:
                barrier.wait()

        def forecasts(self, history, horizon):
            self.enter("forecast" if horizon == 5 else "walkforward")
            return super().forecasts(history, horizon)

        def cause(self, vector):
            self.enter("cause")
            return super().cause(vector)

        def anomaly(self, vector):
            self.enter("anomaly")
            return super().anomaly(vector)

    actual = run_engine(
        probes, interfaces, site_id="test", as_of=probes.time.max(), backend=ConcurrentBackend()
    )
    assert set(entered) == {"forecast", "walkforward", "cause", "anomaly"}
    assert actual == expected


def test_custom_backend_keeps_sequential_call_order_without_opt_in():
    probes, interfaces = observations()
    entered = []

    class SerialBackend(FixtureBackend):
        def forecasts(self, history, horizon):
            entered.append(f"forecast:{horizon}")
            return super().forecasts(history, horizon)

        def cause(self, vector):
            entered.append("cause")
            return super().cause(vector)

        def anomaly(self, vector):
            entered.append("anomaly")
            return super().anomaly(vector)

    run_engine(probes, interfaces, site_id="test", as_of=probes.time.max(), backend=SerialBackend())
    assert entered == ["forecast:5", "forecast:1", "forecast:1", "forecast:1", "cause", "anomaly"]


def test_parallel_failure_never_returns_partial_detection():
    probes, interfaces = observations()

    class FailingBackend(FixtureBackend):
        supports_parallel_inference = True

        def anomaly(self, vector):
            raise RuntimeError("provider unavailable")

    with pytest.raises(DetectorUnavailable, match="inference failed"):
        run_engine(
            probes, interfaces, site_id="test", as_of=probes.time.max(), backend=FailingBackend()
        )
