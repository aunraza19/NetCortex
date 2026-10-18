"""Lead Gate 2 SQL-boundary test; it does not contact the shared database."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path

from netcortex_core import IFACE_COLUMNS, PROBE_COLUMNS, SUBSCRIBER_COLUMNS, MetricsWindow


def test_fetch_window_is_site_source_and_time_bounded():
    module = run_path(str(Path(__file__).resolve().parents[3] / "eval" / "gate2.py"))
    at = datetime(2026, 10, 18, 12, tzinfo=UTC)
    start = at - timedelta(minutes=30)
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))
            self.sql = sql

        def fetchall(self):
            if "probe_metrics" in self.sql:
                row = dict(
                    time=at,
                    site_id="north-tower",
                    target="1.1.1.1",
                    kind="icmp",
                    rtt_ms=20.0,
                    jitter_ms=1.0,
                    loss_pct=0.0,
                    source="sim",
                )
                return [tuple(row[c] for c in PROBE_COLUMNS)]
            if "iface_metrics" in self.sql:
                row = dict(
                    time=at,
                    site_id="north-tower",
                    iface="ether1",
                    rx_bps=10,
                    tx_bps=10,
                    util_pct=20.0,
                    drops=0,
                    errors=0,
                    source="sim",
                )
                return [tuple(row[c] for c in IFACE_COLUMNS)]
            row = dict(
                time=at, site_id="north-tower", ip="192.0.2.10", rx_bps=10, tx_bps=10, source="sim"
            )
            return [tuple(row[c] for c in SUBSCRIBER_COLUMNS)]

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

    result = module["fetch_window"](Connection(), "north-tower", start, at)
    assert isinstance(result, MetricsWindow) and result.as_of == at
    assert len(calls) == 3
    for sql, params in calls:
        normalized = " ".join(sql.lower().split())
        assert "site_id" in normalized and "source" in normalized
        assert "time >=" in normalized and "time <=" in normalized
        assert "north-tower" in params and start in params and at in params
        assert "sim" in params or "source = 'sim'" in normalized or "source='sim'" in normalized
