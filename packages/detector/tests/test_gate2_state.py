"""Offline state/resume tests for the separate credentialed Gate 2 runner."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path

import netcortex_simgen.simulator as simulator
import pandas as pd
from netcortex_core import Cause, ScenarioLabel, Source, TemplateId

RUNNER = run_path(str(Path(__file__).resolve().parents[3] / "eval" / "gate2.py"))


def _label() -> ScenarioLabel:
    start = datetime(2026, 10, 18, 12, tzinfo=UTC)
    return ScenarioLabel(
        site_id="north-tower",
        scenario_type=Cause.UPLINK_CONGESTION,
        start_at=start,
        end_at=start + timedelta(minutes=15),
        affected={"iface": "ether1"},
        expected_cause=Cause.UPLINK_CONGESTION,
        expected_template=TemplateId.PRIORITY_QUEUE,
        expected_params={"uplink": "ether1", "uplink_mbps": 162},
        seed=20261018,
        source=Source.SIM,
    )


def test_resume_state_round_trip_and_requires_matching_database_label(tmp_path):
    label = _label()
    state_path = tmp_path / "state.json"
    state = RUNNER["_load_state"](state_path)
    RUNNER["_save_state"](state_path, state, label)
    loaded = RUNNER["_load_state"](state_path)

    values = (
        label.id,
        label.site_id,
        label.scenario_type.value,
        label.start_at,
        label.end_at,
        label.affected,
        label.expected_cause.value,
        label.expected_template.value,
        label.expected_params,
        label.seed,
        label.source.value,
    )
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchone(self):
            return values

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

    resumed = RUNNER["_resume_active_label"](
        Connection(),
        loaded,
        site_id="north-tower",
        seed=20261018,
        now=label.start_at + timedelta(seconds=12),
    )
    assert resumed == label
    assert "source = 'sim'" in calls[0][0]
    assert calls[0][1] == (str(label.id), "north-tower")


def test_resume_state_does_not_resume_expired_or_foreign_labels(tmp_path):
    label = _label()
    state_path = tmp_path / "state.json"
    state = RUNNER["_load_state"](state_path)
    RUNNER["_save_state"](state_path, state, label)

    class Connection:
        @contextmanager
        def cursor(self):
            class Cursor:
                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def execute(self, *_):
                    pass

                def fetchone(self):
                    return None

            yield Cursor()

    assert (
        RUNNER["_resume_active_label"](
            Connection(), state, site_id="north-tower", seed=20261018, now=label.end_at
        )
        is None
    )
    assert (
        RUNNER["_resume_active_label"](
            Connection(), state, site_id="north-tower", seed=8, now=label.start_at
        )
        is None
    )


def test_history_seeding_skips_rows_inside_existing_scenario(monkeypatch):
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    start = now - timedelta(minutes=60)
    fault_start = start + timedelta(minutes=1)
    fault_end = start + timedelta(minutes=3)

    class Cursor:
        def __init__(self):
            self.sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, _params=None):
            self.sql = sql

        def fetchall(self):
            if "FROM scenario_labels" in self.sql:
                return [(fault_start, fault_end)]
            return []

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

    probes = pd.DataFrame(
        [
            {
                "time": start,
                "site_id": "north-tower",
                "target": "1.1.1.1",
                "kind": "icmp",
                "rtt_ms": 20.0,
                "jitter_ms": 1.0,
                "loss_pct": 0.0,
                "source": "sim",
            },
            {
                "time": fault_start,
                "site_id": "north-tower",
                "target": "1.1.1.1",
                "kind": "icmp",
                "rtt_ms": 20.0,
                "jitter_ms": 1.0,
                "loss_pct": 0.0,
                "source": "sim",
            },
        ]
    )
    interfaces = pd.DataFrame(
        [
            {
                "time": start,
                "site_id": "north-tower",
                "iface": "ether1",
                "rx_bps": 1,
                "tx_bps": 1,
                "util_pct": 20.0,
                "drops": 0,
                "errors": 0,
                "source": "sim",
            },
            {
                "time": fault_start,
                "site_id": "north-tower",
                "iface": "ether1",
                "rx_bps": 1,
                "tx_bps": 1,
                "util_pct": 20.0,
                "drops": 0,
                "errors": 0,
                "source": "sim",
            },
        ]
    )
    subscribers = pd.DataFrame(
        [
            {
                "time": start,
                "site_id": "north-tower",
                "ip": "192.0.2.10",
                "rx_bps": 1,
                "tx_bps": 1,
                "source": "sim",
            },
            {
                "time": fault_start,
                "site_id": "north-tower",
                "ip": "192.0.2.10",
                "rx_bps": 1,
                "tx_bps": 1,
                "source": "sim",
            },
        ]
    )
    monkeypatch.setattr(simulator, "generate", lambda **_: (probes, interfaces, []))
    monkeypatch.setattr(simulator, "generate_subscribers", lambda *_, **__: subscribers)
    monkeypatch.setattr(RUNNER["core_db"], "fetch_site", lambda *_: object())
    inserted = {"probe": [], "iface": [], "subscriber": []}
    monkeypatch.setattr(
        RUNNER["core_db"], "insert_probe_metrics", lambda _, rows: inserted["probe"].extend(rows)
    )
    monkeypatch.setattr(
        RUNNER["core_db"], "insert_iface_metrics", lambda _, rows: inserted["iface"].extend(rows)
    )
    monkeypatch.setattr(
        RUNNER["core_db"],
        "insert_subscriber_metrics",
        lambda _, rows: inserted["subscriber"].extend(rows),
    )

    result = RUNNER["_seed_normal_history"](Connection(), site_id="north-tower", now=now, seed=5)
    assert result["probe_rows_added"] == result["iface_rows_added"] == 1
    assert result["subscriber_rows_added"] == 1
    assert all(row.time == start for rows in inserted.values() for row in rows)
