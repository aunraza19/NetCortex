"""Lead acceptance for the CHR-compatible runtime simulator."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from netcortex_core import Cause, IfaceMetric, ProbeMetric, ScenarioLabel, SubscriberMetric
from netcortex_simgen import simulator


def test_sim_tower_matches_canonical_chr_topology():
    site = simulator.site_from_fixture("sim-tower")
    assert {u.iface: u.gateway for u in site.uplinks} == {
        "ether1": "10.0.2.2",
        "ether2": "192.0.2.1",
    }
    assert {"dns:192.0.2.53", "dns:1.1.1.1", "10.0.0.1"} <= {t.key for t in site.targets}


@pytest.mark.parametrize("cause", [Cause.HEAVY_USER, Cause.DNS_SLOW, Cause.UPLINK_DOWN])
def test_runtime_injection_has_normal_incident_and_scripted_recovery(monkeypatch, cause):
    captured = {"probe": [], "iface": [], "subscriber": []}

    class Cursor:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            return (None,) if "max(time)" in self.sql.lower() else None

        def fetchall(self):
            return []

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

        @contextmanager
        def transaction(self):
            yield

    class Pool:
        @contextmanager
        def connection(self):
            yield Connection()

    monkeypatch.setattr(simulator.core_db, "fetch_site", lambda *args: None)
    monkeypatch.setattr(simulator.core_db, "upsert_site", lambda *args: None)
    for name in captured:
        monkeypatch.setattr(
            simulator.core_db,
            f"insert_{name}_metrics",
            lambda conn, rows, key=name: captured[key].extend(rows),
        )
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    label = simulator.inject("sim-tower", cause, 2, 71, now=now, database=Pool())
    assert isinstance(label, ScenarioLabel)
    for name, kind in (
        ("probe", ProbeMetric),
        ("iface", IfaceMetric),
        ("subscriber", SubscriberMetric),
    ):
        rows = captured[name]
        assert rows and all(isinstance(row, kind) and row.source.value == "sim" for row in rows)
        assert min(row.time for row in rows) < now
        assert max(row.time for row in rows) > label.end_at
        assert max(row.time for row in rows) <= label.end_at + timedelta(minutes=20)
    assert {r.ip for r in captured["subscriber"]} >= {"10.0.0.42", "10.0.0.57", "10.0.0.63"}
    incident = [r for r in captured["probe"] if now <= r.time < label.end_at]
    if cause == Cause.DNS_SLOW:
        assert max(r.rtt_ms or 0 for r in incident if r.target == "dns:192.0.2.53") > 400
        assert all(r.kind.value == "dns" for r in incident if r.target.startswith("dns:"))
    elif cause == Cause.HEAVY_USER:
        assert label.affected["ip"] == "10.0.0.42"
        assert max(r.rx_bps for r in captured["subscriber"] if now <= r.time < label.end_at) > 100e6
    else:
        assert label.expected_params["primary_gateway"] == "10.0.2.2"
        assert label.expected_params["backup_gateway"] == "192.0.2.1"
        assert all(r.loss_pct == 100 for r in incident if r.target == "1.1.1.1")
