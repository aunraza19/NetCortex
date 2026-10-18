import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import netcortex_simgen.simulator as simulator
import pandas as pd
import pytest
from netcortex_simgen import inject
from netcortex_simgen.cli import _build_calibration, _read_target_role_map, make_eval_cases
from netcortex_simgen.ripe import parse_result
from netcortex_simgen.simulator import (
    CAUSES,
    generate,
    generate_supplemental,
    inject_frames,
)


def test_seed_reproducible_and_schema_cadence():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    p1, i1, _ = generate(days=1, seed=7, start=start, normal_only=True)
    p2, i2, _ = generate(days=1, seed=7, start=start, normal_only=True)
    pd.testing.assert_frame_equal(p1, p2)
    pd.testing.assert_frame_equal(i1, i2)
    assert p1.groupby(["site_id", "target"]).size().eq(8640).all()
    assert i1.groupby(["site_id", "iface"]).size().eq(2880).all()
    assert p1.time.dt.tz is not None and set(p1.source) == {"sim"}
    assert p1.loss_pct.between(0, 100).all() and p1.rtt_ms.gt(0).all()


def test_core_site_mapping_and_subscribers_have_healthy_and_active_rows():
    site = simulator.site_from_fixture("market-cafe")
    assert [uplink.role.value for uplink in site.uplinks] == ["primary", "backhaul"]
    assert all(target.role.value for target in site.targets)
    assert not any(uplink.role.value == "backup" for uplink in site.uplinks)
    start = datetime(2026, 10, 12, tzinfo=UTC)
    label = {
        "site_id": "north-tower",
        "cause": "heavy_user",
        "start": start + pd.Timedelta(minutes=1),
        "end": start + pd.Timedelta(minutes=2),
    }
    rows = simulator.generate_subscribers(
        [label], start=start, end=start + pd.Timedelta(minutes=3), site_ids=["north-tower"]
    )
    assert rows.time.min() < label["start"]
    assert rows.loc[rows.time >= label["start"], "rx_bps"].max() > 10_000_000


def test_scenario_labels_match_template_parameter_contracts():
    from netcortex_fixes import validate

    site = simulator.sites()["sites"][0]
    start = datetime(2026, 10, 12, tzinfo=UTC)
    for cause in CAUSES:
        label = simulator._label(site, cause, start, start + pd.Timedelta(minutes=15), 9)
        if label["template_id"] == "none":
            assert label["params"] == {}
        else:
            validate(label["template_id"], label["params"])

    gateway_site = {
        **site,
        "uplinks": [{**site["uplinks"][0], "gateway": "192.0.2.1"}],
        "backup_uplink": {**site["backup_uplink"], "gateway": "192.0.2.2"},
    }
    failover = simulator._label(
        gateway_site, "uplink_down", start, start + pd.Timedelta(minutes=15), 10
    )
    assert failover["template_id"] == "failover_route"
    validate(failover["template_id"], failover["params"])


class _Transaction:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.conn.rolled_back = exc_type is not None
        return False


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        self.conn.last_overlap = "SELECT 1 FROM scenario_labels" in sql

    def fetchone(self):
        return (1,) if self.conn.overlap and self.conn.last_overlap else None


class _Conn:
    def __init__(self, overlap=False):
        self.overlap = overlap
        self.rolled_back = False
        self.sql = []

    def cursor(self):
        return _Cursor(self)

    def transaction(self):
        return _Transaction(self)


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def connection(self):
        class Connection:
            def __enter__(_self):
                return self.conn

            def __exit__(_self, *_):
                return False

        return Connection()


def test_public_inject_preserves_site_and_rolls_back_on_failure(monkeypatch):
    now = datetime(2026, 10, 12, tzinfo=UTC)
    conn = _Conn()
    upserted_sites = []
    monkeypatch.setattr(
        simulator.core_db, "fetch_site", lambda *_: simulator.site_from_fixture("north-tower")
    )
    monkeypatch.setattr(
        simulator.core_db, "upsert_site", lambda _conn, site: upserted_sites.append(site)
    )
    monkeypatch.setattr(simulator.core_db, "insert_probe_metrics", lambda *_: 1)
    monkeypatch.setattr(simulator.core_db, "insert_iface_metrics", lambda *_: 1)
    monkeypatch.setattr(simulator.core_db, "insert_subscriber_metrics", lambda *_: 1)
    monkeypatch.setattr(
        simulator,
        "generate",
        lambda **kwargs: (
            pd.DataFrame(
                [
                    {
                        "time": now,
                        "site_id": "north-tower",
                        "target": "1.1.1.1",
                        "kind": "icmp",
                        "rtt_ms": 20.0,
                        "jitter_ms": 1.0,
                        "loss_pct": 0.0,
                        "source": "sim",
                    }
                ]
            ),
            pd.DataFrame(
                columns=[
                    "time",
                    "site_id",
                    "iface",
                    "rx_bps",
                    "tx_bps",
                    "util_pct",
                    "drops",
                    "errors",
                    "source",
                ]
            ),
            [
                simulator._label(
                    simulator.sites()["sites"][0],
                    kwargs["scenario_type"],
                    now,
                    now + pd.Timedelta(minutes=kwargs["duration_min"]),
                    kwargs["seed"],
                )
            ],
        ),
    )
    label = simulator.inject(
        "north-tower", "uplink_congestion", 2, 8, now=now, database=_Pool(conn)
    )
    assert label.start_at == now and label.end_at == now + pd.Timedelta(minutes=2)
    assert not conn.rolled_back
    assert not upserted_sites
    assert any("pg_advisory_xact_lock" in sql for sql in conn.sql)
    assert any("INSERT INTO scenario_labels" in sql for sql in conn.sql)
    assert not any("CREATE " in sql for sql in conn.sql)
    with pytest.raises(ValueError, match="1320"):
        simulator.inject("north-tower", "uplink_congestion", 1321, 8, now=now, database=_Pool(conn))
    with pytest.raises(ValueError, match="unknown site"):
        simulator.inject("missing-site", "uplink_congestion", 2, 8, now=now, database=_Pool(conn))

    overlap_conn = _Conn(overlap=True)
    with pytest.raises(ValueError, match="overlaps"):
        simulator.inject(
            "north-tower", "uplink_congestion", 2, 8, now=now, database=_Pool(overlap_conn)
        )
    assert overlap_conn.rolled_back

    monkeypatch.setattr(
        simulator.core_db,
        "insert_probe_metrics",
        lambda *_: (_ for _ in ()).throw(RuntimeError("db failure")),
    )
    failed_conn = _Conn()
    with pytest.raises(RuntimeError, match="db failure"):
        simulator.inject(
            "north-tower", "uplink_congestion", 2, 8, now=now, database=_Pool(failed_conn)
        )
    assert failed_conn.rolled_back


def test_packaged_site_resource_works_without_repository_root(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setattr(simulator, "ROOT", tmp_path)
    layout = simulator.sites()
    canonical_path = Path(simulator.__file__).resolve().parents[4] / "data" / "sites.yaml"
    canonical = yaml.safe_load(canonical_path.read_text())
    assert layout == canonical
    p, _, _ = generate(days=1, hours=1, seed=2, site_id="north-tower", normal_only=True)
    assert len(p) == 360 * 6


def test_scenarios_distinguishable_and_labelled():
    p0, _, _ = generate(days=1, seed=8, site_id="north-tower", normal_only=True)
    for cause in CAUSES:
        p, iface, labels = inject_frames(
            "north-tower", cause, 15, 8, datetime(2026, 10, 1, tzinfo=UTC)
        )
        label = labels
        affected = p[(p.time >= label["start"]) & (p.time < label["end"])]
        assert len(affected) > 0 and affected.loss_pct.between(0, 100).all()
        if cause == "uplink_down":
            outside = affected[(affected.kind == "icmp") & (affected.target != "gateway")]
            assert outside.loss_pct.mean() >= 95
            assert outside.loss_pct.eq(100).all()
            assert outside.rtt_ms.isna().all()
            assert "ether2" in set(iface.iface)
        elif cause == "game_route_issue":
            assert (
                affected[affected.target == "regional-game"].rtt_ms.mean()
                > affected[affected.target == "1.1.1.1"].rtt_ms.mean()
            )
        elif cause == "upstream_degradation":
            assert (
                affected[affected.target == "1.1.1.1"].rtt_ms.mean()
                > p0[p0.target == "1.1.1.1"].rtt_ms.mean()
            )
        elif cause == "wireless_interference":
            assert iface[iface.iface == "wlan1"].errors.sum() > 0
        elif cause == "uplink_congestion":
            affected_ifaces = iface[(iface.time >= label["start"]) & (iface.time < label["end"])]
            assert affected_ifaces[affected_ifaces.iface == "ether1"].util_pct.mean() > 95
        elif cause == "dns_slow":
            extra = generate_supplemental(
                [label],
                start=label["start"] - pd.Timedelta(hours=1),
                end=label["end"],
                seed=8,
                site_ids=["north-tower"],
            )
            dns = extra[extra.kind == "dns_resolution"]
            assert dns.latency_ms.max() > 300 and dns.latency_ms.min() < 40
        elif cause == "heavy_user":
            extra = generate_supplemental(
                [label],
                start=label["start"] - pd.Timedelta(hours=1),
                end=label["end"],
                seed=8,
                site_ids=["north-tower"],
            )
            traffic = extra[extra.kind == "subscriber_traffic"]
            assert traffic.rx_bps.max() > 50_000_000 and traffic.rx_bps.min() < 10_000_000


def test_public_inject_reports_missing_database(monkeypatch):
    from netcortex_core import ModuleUnavailable

    settings = simulator.Settings
    monkeypatch.setattr(simulator, "Settings", lambda: settings(_env_file=None))
    with pytest.raises(ModuleUnavailable, match="DATABASE_URL"):
        inject("north-tower", "uplink_congestion", 15, 4)


def test_pk_hour_calibration_is_used_and_utc_stays_on_output(monkeypatch, tmp_path):
    source_root = simulator.ROOT
    (tmp_path / "data").mkdir()
    shutil.copy(source_root / "data/sites.yaml", tmp_path / "data/sites.yaml")
    (tmp_path / "data/calibration.json").write_text(
        json.dumps(
            {
                "provenance": ["recorded fixture"],
                "target_medians_ms": {"1.1.1.1": 200.0},
                "target_hourly_ms": {"1.1.1.1": {"12": 300.0}},
            }
        )
    )
    monkeypatch.setattr(simulator, "ROOT", tmp_path)
    # 07:00 UTC is 12:00 in Pakistan.
    p, _, _ = generate(
        days=1,
        hours=1,
        seed=91,
        start=datetime(2026, 10, 1, 7, tzinfo=UTC),
        site_id="north-tower",
        normal_only=True,
    )
    probe = p[p.target == "1.1.1.1"]
    assert probe.rtt_ms.median() == pytest.approx(300.0, abs=3.0)
    assert probe.time.dt.hour.eq(7).all()


def test_external_ripe_targets_do_not_calibrate_unrelated_simulator_targets(monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    shutil.copy(simulator.ROOT / "data/sites.yaml", tmp_path / "data/sites.yaml")
    (tmp_path / "data/calibration.json").write_text(
        json.dumps(
            {
                "provenance": ["RIPE public DNS-server reachability"],
                "target_medians_ms": {"192.5.5.241": 999.0},
                "target_hourly_ms": {"192.5.5.241": {"12": 888.0}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(simulator, "ROOT", tmp_path)
    p, _, _ = generate(
        days=1,
        hours=1,
        seed=92,
        start=datetime(2026, 10, 1, 7, tzinfo=UTC),
        site_id="north-tower",
        normal_only=True,
    )
    assert p[p.target == "1.1.1.1"].rtt_ms.median() == pytest.approx(28.0, abs=3.0)
    assert p[p.target == "8.8.8.8"].rtt_ms.median() == pytest.approx(35.0, abs=3.0)


def test_calibration_uses_target_hour_medians_and_keeps_observed_stats():

    observed = pd.DataFrame(
        {
            "time": pd.to_datetime(
                [
                    "2026-10-01T08:00:00Z",
                    "2026-10-01T08:10:00Z",
                    "2026-10-01T09:00:00Z",
                ]
            ),
            "target": ["1.1.1.1", "1.1.1.1", "8.8.8.8"],
            "target_role": ["unmapped_ripe_public_ping"] * 3,
            "rtt_ms": [10.0, 200.0, 40.0],
            "jitter_ms": [2.0, 4.0, 8.0],
            "loss_pct": [0.0, 20.0, 10.0],
            "source": ["ripe"] * 3,
        }
    )
    calibration = _build_calibration(
        observed,
        {"1.1.1.1": "public_dns_reachability_proxy"},
    )
    stats = calibration["target_hourly_stats"]["1.1.1.1"]["13"]
    assert calibration["target_hourly_ms"]["1.1.1.1"]["13"] == 105.0
    assert stats == {"sample_count": 2, "rtt_ms": 105.0, "jitter_ms": 3.0, "loss_pct": 10.0}
    assert calibration["target_roles"]["1.1.1.1"] == "public_dns_reachability_proxy"
    assert calibration["target_roles"]["8.8.8.8"] == "unmapped_ripe_public_ping"
    assert "DNS resolution timing" in calibration["experimental_status"]
    assert not calibration["role_proxy"]["enabled"]
    assert calibration["role_medians"]["public_dns_reachability_proxy"]["sample_count"] == 2
    assert calibration["role_hourly_stats"]["public_dns_reachability_proxy"]["13"] == {
        "sample_count": 2,
        "rtt_ms": 105.0,
        "jitter_ms": 3.0,
        "loss_pct": 10.0,
    }


def test_role_proxy_requires_both_explicit_mapping_and_opt_in(monkeypatch, tmp_path):
    observed = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-10-01T08:00:00Z", "2026-10-01T08:10:00Z"]),
            "target": ["192.5.5.241", "193.0.14.129"],
            "rtt_ms": [16.0, 18.0],
            "jitter_ms": [0.4, 0.6],
            "loss_pct": [0.0, 2.0],
            "source": ["ripe", "ripe"],
        }
    )
    mapping = {
        "192.5.5.241": "public_dns_reachability_proxy",
        "193.0.14.129": "public_dns_reachability_proxy",
    }
    without_flag = _build_calibration(observed, mapping)
    opted_in = _build_calibration(observed, mapping, allow_role_proxy=True)
    assert without_flag["role_proxy"]["enabled"] is False
    assert opted_in["role_proxy"]["enabled"] is True
    assert opted_in["role_proxy"]["source_targets"] == sorted(mapping)
    assert opted_in["role_medians"]["public_dns_reachability_proxy"] == {
        "sample_count": 2,
        "rtt_ms": 17.0,
        "jitter_ms": 0.5,
        "loss_pct": 1.0,
    }
    (tmp_path / "data").mkdir()
    shutil.copy(simulator.ROOT / "data/sites.yaml", tmp_path / "data/sites.yaml")
    calibration_path = tmp_path / "data/calibration.json"
    calibration_path.write_text(json.dumps(without_flag), encoding="utf-8")
    monkeypatch.setattr(simulator, "ROOT", tmp_path)
    kwargs = {
        "days": 1,
        "hours": 1,
        "seed": 94,
        "start": datetime(2026, 10, 1, 7, tzinfo=UTC),
        "site_id": "north-tower",
        "normal_only": True,
    }
    defaulted, _, _ = generate(**kwargs)
    assert defaulted.attrs["calibration"]["target_modes"]["1.1.1.1"] == "illustrative_default"
    calibration_path.write_text(json.dumps(opted_in), encoding="utf-8")
    proxied, _, _ = generate(**kwargs)
    assert proxied.attrs["calibration"]["target_modes"]["1.1.1.1"] == "explicit_role_proxy"


def test_role_proxy_applies_only_dns_reachability_targets_and_exact_target_wins(
    monkeypatch, tmp_path
):
    (tmp_path / "data").mkdir()
    shutil.copy(simulator.ROOT / "data/sites.yaml", tmp_path / "data/sites.yaml")
    (tmp_path / "data/calibration.json").write_text(
        json.dumps(
            {
                "provenance": ["RIPE public DNS-server reachability"],
                "target_roles": {
                    "192.5.5.241": "public_dns_reachability_proxy",
                    "193.0.14.129": "public_dns_reachability_proxy",
                },
                "target_medians_ms": {"8.8.8.8": 40.0},
                "target_stats": {"8.8.8.8": {"rtt_ms": 40.0, "jitter_ms": 9.0, "loss_pct": 1.0}},
                "target_hourly_stats": {
                    "8.8.8.8": {"12": {"rtt_ms": 50.0, "jitter_ms": 8.0, "loss_pct": 2.0}}
                },
                "role_medians": {
                    "public_dns_reachability_proxy": {
                        "sample_count": 100,
                        "rtt_ms": 76.0,
                        "jitter_ms": 5.0,
                        "loss_pct": 3.0,
                    }
                },
                "role_hourly_stats": {
                    "public_dns_reachability_proxy": {
                        "12": {
                            "sample_count": 10,
                            "rtt_ms": 100.0,
                            "jitter_ms": 7.0,
                            "loss_pct": 4.0,
                        }
                    }
                },
                "role_proxy": {
                    "enabled": True,
                    "role": "public_dns_reachability_proxy",
                    "source_targets": ["192.5.5.241", "193.0.14.129"],
                    "configured_targets": ["1.1.1.1", "8.8.8.8"],
                    "uncertainty": "Root DNS reachability does not prove route equivalence.",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(simulator, "ROOT", tmp_path)
    p, _, _ = generate(
        days=1,
        hours=1,
        seed=93,
        start=datetime(2026, 10, 1, 7, tzinfo=UTC),
        site_id="north-tower",
        normal_only=True,
    )
    dns1 = p[p.target == "1.1.1.1"]
    dns8 = p[p.target == "8.8.8.8"]
    assert dns1.rtt_ms.median() > dns8.rtt_ms.median() + 30
    assert dns1.jitter_ms.median() > 7.0
    assert dns1.loss_pct.median() == pytest.approx(4.0, abs=0.2)
    assert p[p.target == "gateway"].rtt_ms.median() < 5
    assert p[p.target == "regional-game"].rtt_ms.median() < 100
    metadata = p.attrs["calibration"]
    assert metadata["target_modes"]["1.1.1.1"] == "explicit_role_proxy"
    assert metadata["target_modes"]["8.8.8.8"] == "exact_target"
    assert metadata["target_modes"]["gateway"] == "illustrative_default"
    assert metadata["role_proxy"]["applied_to"] == ["1.1.1.1"]
    assert "does not prove route equivalence" in metadata["role_proxy"]["uncertainty"]
    from netcortex_simgen.cli import _write

    output = tmp_path / "generated"
    _write(p, pd.DataFrame(), [], output)
    generation_metadata = json.loads((output / "generation_metadata.json").read_text())
    assert generation_metadata["calibration"]["role_proxy"]["applied_to"] == ["1.1.1.1"]


def test_target_role_map_rejects_dns_resolution_role(tmp_path):
    mapping = tmp_path / "roles.json"
    mapping.write_text('{"1.1.1.1":"dns_resolution"}', encoding="utf-8")
    with pytest.raises(ValueError, match="ping observations"):
        _read_target_role_map(mapping)


def test_ripe_loss_and_bad_rtts():
    total = parse_result({"timestamp": 10, "sent": 5, "rcvd": 0, "rtts": []})
    assert total and total["loss_pct"] == 100 and total["rtt_ms"] is None
    mixed = parse_result(
        {
            "timestamp": 10,
            "sent": 4,
            "result": [{"rtt": 10}, {"x": "*"}, {}, {"rtt": 14}],
        }
    )
    assert mixed and mixed["loss_pct"] == 50 and mixed["rtt_ms"] == 12
    assert parse_result({"timestamp": "broken", "sent": 1}) is None


def test_ripe_fetch_discovers_and_caches_results_offline(monkeypatch, tmp_path):
    from netcortex_simgen import ripe

    calls = []

    def handler(request):
        calls.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/probes/"):
            payload = {"results": [{"id": 17}], "next": None}
        elif request.url.path.endswith("/measurements/"):
            payload = {"results": [{"id": 91}], "next": None}
        elif request.url.path.endswith("/results/"):
            payload = {
                "results": [
                    {
                        "timestamp": 1_800_000_000,
                        "sent": 4,
                        "rtts": [{"rtt": 10}, {"rtt": 14}],
                        "dst_addr": "1.1.1.1",
                        "prb_id": 17,
                    }
                ],
                "next": None,
            }
        else:
            raise AssertionError(f"unexpected RIPE path: {request.url.path}")
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(ripe.time, "time", lambda: 1_800_000_000)
    monkeypatch.setattr(ripe.time, "sleep", lambda _seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    first = ripe.fetch(1, cache_dir=tmp_path, client=client, max_measurements=1)
    second = ripe.fetch(1, cache_dir=tmp_path, client=client, max_measurements=1)
    assert len(first) == len(second) == 1
    assert first.iloc[0].source == "ripe" and first.iloc[0].probe_id == 17
    results = [params for path, params in calls if path.endswith("/results/")]
    discovery = [params for path, params in calls if path.endswith("/measurements/")]
    assert len(results) == 1
    assert results[0]["start"] == str(1_800_000_000 // 86400 * 86400 - 86400)
    assert results[0]["stop"] == str(1_800_000_000 // 86400 * 86400)
    assert results[0]["probe_ids"] == "17"
    assert "probe_ids" not in discovery[0]
    client.close()


def test_ripe_fetch_requests_each_utc_day_and_records_day_gaps(monkeypatch, tmp_path):
    from netcortex_simgen import ripe

    requests = []

    def handler(request):
        if request.url.path.endswith("/probes/"):
            return httpx.Response(
                200, json={"results": [{"id": 17, "asn_v4": 64500}], "next": None}
            )
        if request.url.path.endswith("/measurements/"):
            return httpx.Response(
                200, json={"results": [{"id": 91, "target_ip": "1.1.1.1"}], "next": None}
            )
        if request.url.path.endswith("/results/"):
            params = dict(request.url.params)
            requests.append(params)
            if len(requests) == 1:
                raise httpx.ReadTimeout("recorded first-day timeout")
            return httpx.Response(
                200,
                json=[
                    {
                        "timestamp": int(params["start"]) + 120,
                        "sent": 1,
                        "rcvd": 1,
                        "avg": 12.0,
                        "dst_addr": "1.1.1.1",
                        "prb_id": 17,
                    }
                ],
            )
        raise AssertionError(request.url)

    now = 1_800_000_000 // 86400 * 86400
    monkeypatch.setattr(ripe.time, "time", lambda: now + 100)
    monkeypatch.setattr(ripe.time, "sleep", lambda _seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    frame = ripe.fetch(2, cache_dir=tmp_path, client=client, max_measurements=1, max_probes=1)
    report = frame.attrs["ripe_fetch_report"]
    assert [int(params["start"]) for params in requests] == [now - 2 * 86400, now - 86400]
    assert all(int(item["stop"]) - int(item["start"]) == 86400 for item in requests)
    assert report["status"] == "partial"
    assert (
        report["days"][pd.Timestamp(now - 2 * 86400, unit="s", tz="UTC").strftime("%Y-%m-%d")][
            "status"
        ]
        == "failed"
    )
    assert (
        report["days"][pd.Timestamp(now - 86400, unit="s", tz="UTC").strftime("%Y-%m-%d")]["status"]
        == "complete"
    )
    assert len(report["failed_daily_measurement_requests"]) == 1
    client.close()


def test_ripe_result_cache_key_includes_selected_probe_ids(monkeypatch, tmp_path):
    from netcortex_simgen import ripe

    result_calls = []

    def handler(request):
        path = request.url.path
        if path.endswith("/probes/"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": 17, "asn_v4": 64500},
                        {"id": 18, "asn_v4": 64501},
                    ],
                    "next": None,
                },
            )
        if path.endswith("/measurements/"):
            return httpx.Response(200, json={"results": [{"id": 91}], "next": None})
        if path.endswith("/results/"):
            params = dict(request.url.params)
            result_calls.append(params["probe_ids"])
            return httpx.Response(200, json=[])
        raise AssertionError(request.url)

    monkeypatch.setattr(ripe.time, "time", lambda: 1_800_000_000)
    monkeypatch.setattr(ripe.time, "sleep", lambda _seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    ripe.fetch(1, cache_dir=tmp_path, client=client, max_measurements=1, max_probes=1)
    ripe.fetch(1, cache_dir=tmp_path, client=client, max_measurements=1, max_probes=2)
    assert result_calls == ["17", "17,18"]
    assert len(list(tmp_path.glob("measurement-91-*.json"))) == 2
    client.close()


def test_ripe_missing_provider_is_empty_and_reports_no_data(monkeypatch, tmp_path):
    from netcortex_simgen import ripe

    def handler(request):
        assert request.url.path.endswith("/probes/")
        return httpx.Response(200, json={"results": [], "next": None})

    monkeypatch.setattr(ripe.time, "sleep", lambda _seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    frame = ripe.fetch(1, cache_dir=tmp_path, client=client)
    assert frame.empty
    assert frame.attrs["ripe_fetch_report"]["status"] == "no_active_probes"
    assert not list(tmp_path.glob("measurement-*.json"))
    client.close()


def test_ripe_empty_measurement_discovery_reports_no_measurements(monkeypatch, tmp_path):
    from netcortex_simgen import ripe

    def handler(request):
        if request.url.path.endswith("/probes/"):
            return httpx.Response(200, json={"results": [{"id": 17}], "next": None})
        assert request.url.path.endswith("/measurements/")
        return httpx.Response(200, json={"results": [], "next": None})

    monkeypatch.setattr(ripe.time, "sleep", lambda _seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    frame = ripe.fetch(1, cache_dir=tmp_path, client=client)
    assert frame.empty
    assert frame.attrs["ripe_fetch_report"]["status"] == "no_measurements"
    assert not list(tmp_path.glob("measurement-*.json"))
    client.close()


def test_ripe_malformed_discovery_is_rejected(monkeypatch, tmp_path):
    from netcortex_simgen import ripe

    def handler(_request):
        return httpx.Response(200, json={"unexpected": []})

    monkeypatch.setattr(ripe.time, "sleep", lambda _seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(TypeError, match="paginated response"):
        ripe.fetch(1, cache_dir=tmp_path, client=client)
    client.close()


def test_calibrate_mock_never_makes_or_uses_fake_observations(monkeypatch, tmp_path):
    from netcortex_simgen import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="no mock observations are bundled"):
        cli.main(["calibrate", "--mock"])
    assert not (tmp_path / "data/calibration.json").exists()


def test_load_source_selects_correct_rows_and_last_window(monkeypatch, tmp_path):
    from netcortex_simgen import cli

    generated = tmp_path / "data/generated"
    ripe_data = tmp_path / "data/raw/ripe"
    generated.mkdir(parents=True)
    ripe_data.mkdir(parents=True)
    times = pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"])
    sim = pd.DataFrame(
        {
            "time": times,
            "site_id": "north-tower",
            "target": "1.1.1.1",
            "rtt_ms": [10, 11],
            "source": "sim",
        }
    )
    ripe = sim.assign(rtt_ms=[50, 51], source="ripe")
    iface = pd.DataFrame(
        {"time": times, "site_id": "north-tower", "iface": "ether1", "rx_bps": [1, 2]}
    )
    sim.to_parquet(generated / "probe_metrics.parquet")
    iface.to_parquet(generated / "iface_metrics.parquet")
    ripe.to_parquet(ripe_data / "results.parquet")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    p_sim, i_sim = cli._read_source("sim", "12h")
    p_ripe, i_ripe = cli._read_source("ripe", "12h")
    assert p_sim.source.tolist() == ["sim"] and p_sim.rtt_ms.tolist() == [11]
    assert p_ripe.source.tolist() == ["ripe"] and p_ripe.rtt_ms.tolist() == [51]
    assert i_sim.rx_bps.tolist() == [2] and i_ripe.empty


def test_eval_split_and_label_separation(tmp_path):
    make_eval_cases(8, 1000, tmp_path)
    cases = list(tmp_path.glob("*/*.json"))
    assert len(cases) == 24
    from collections import Counter

    found = Counter()
    seeds = {"train": set(), "validation": set(), "test": set()}
    windows = {"train": set(), "validation": set(), "test": set()}
    ranges = {"train": [], "validation": [], "test": []}
    for path in cases:
        import json

        record = json.loads(path.read_text())
        found[record["expected"]["cause"]] += 1
        seeds[record["split"]].add(record["seed"])
        windows[record["split"]].add(record["case_start"])
        ranges[record["split"]].append(
            (pd.Timestamp(record["case_start"]), pd.Timestamp(record["as_of"]))
        )
        features = pd.read_parquet(path.parent / record["observations"]["probe"])
        assert "cause" not in features and "expected" not in features
        assert pd.to_datetime(features.time, utc=True).max() <= pd.Timestamp(record["as_of"])
        assert record["history_window"]["end_exclusive"] == record["detection_window"]["start"]
        assert pd.Timestamp(record["as_of"]) - pd.Timestamp(
            record["detection_window"]["start"]
        ) == pd.Timedelta(minutes=30)
        extra = pd.read_parquet(path.parent / record["observations"]["supplemental"])
        assert set(extra.kind) == {"dns_resolution", "subscriber_traffic", "backhaul_quality"}
    assert found["normal"] == 3 and all(found[c] == 3 for c in CAUSES)
    assert seeds["train"].isdisjoint(seeds["validation"]) and seeds["test"].isdisjoint(
        seeds["train"]
    )
    assert windows["train"].isdisjoint(windows["validation"]) and windows["test"].isdisjoint(
        windows["train"]
    )
    ordered = [
        (
            min(begin for begin, _ in ranges[split]),
            max(end for _, end in ranges[split]),
        )
        for split in ("train", "validation", "test")
    ]
    assert ordered[0][1] < ordered[1][0] < ordered[1][1] < ordered[2][0]
