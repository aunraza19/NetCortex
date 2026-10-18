import asyncio

import pytest
from netcortex_collector import main
from netcortex_core import ProbeKind, Settings, TargetRole


def settings(**overrides) -> Settings:
    values = dict(collector_interval_s=0.01, collector_pings=5, collector_game_server=None)
    return Settings(_env_file=None, **(values | overrides))  # never read the real .env


def test_targets_cover_gateway_upstream_public_game_and_dns():
    targets = main.build_targets(
        settings(collector_game_server="203.0.113.50"), "192.168.1.1", "198.51.100.1"
    )
    assert [(t.key, t.role, t.kind) for t in targets] == [
        ("192.168.1.1", TargetRole.GATEWAY, ProbeKind.ICMP),
        ("198.51.100.1", TargetRole.UPSTREAM_HOP, ProbeKind.ICMP),
        ("1.1.1.1", TargetRole.PUBLIC_DNS, ProbeKind.ICMP),
        ("8.8.8.8", TargetRole.PUBLIC_DNS, ProbeKind.ICMP),
        ("203.0.113.50", TargetRole.GAME_SERVER, ProbeKind.ICMP),
        ("dns:1.1.1.1", TargetRole.PUBLIC_DNS, ProbeKind.DNS),
        ("dns:8.8.8.8", TargetRole.PUBLIC_DNS, ProbeKind.DNS),
    ]


def test_missing_gateway_is_simply_left_out():
    keys = [t.key for t in main.build_targets(settings(), None, None)]
    assert keys == ["1.1.1.1", "8.8.8.8", "dns:1.1.1.1", "dns:8.8.8.8"]


@pytest.fixture
def fake_network(monkeypatch):
    """Pings answer except to 8.8.8.8, whose probe crashes; DNS loses one of five lookups."""

    async def fake_ping(host, count, timeout_s):
        if host == "8.8.8.8":
            raise OSError("network is unreachable")
        return [10.0] * count

    async def fake_dns(resolver, name, count, timeout_s):
        return [20.0] * (count - 1) + [None]

    async def fake_discover(target):
        return "192.168.1.1", "198.51.100.1"

    monkeypatch.setattr(main, "ping_rtts", fake_ping)
    monkeypatch.setattr(main, "dns_rtts", fake_dns)
    monkeypatch.setattr(main, "discover_path", fake_discover)


def test_round_writes_live_rows_and_skips_a_failed_probe(fake_network):
    s = settings()
    targets = main.build_targets(s, "192.168.1.1", None)
    rows = asyncio.run(main.probe_round(targets, s))
    by_target = {row.target: row for row in rows}
    assert "8.8.8.8" not in by_target  # crashed probe: skipped, not reported as 100% loss
    assert by_target["192.168.1.1"].rtt_ms == 10.0 and by_target["192.168.1.1"].loss_pct == 0
    assert by_target["dns:1.1.1.1"].kind is ProbeKind.DNS
    assert by_target["dns:1.1.1.1"].loss_pct == 20.0
    assert {row.source.value for row in rows} == {"live"}
    assert {row.site_id for row in rows} == {"home-lab"}
    assert len({row.time for row in rows}) == 1  # one timestamp per round


def test_run_keeps_going_when_the_database_fails(fake_network, monkeypatch):
    calls = []

    def flaky_save(s, rows):
        calls.append(len(rows))
        if len(calls) == 1:
            raise ConnectionError("database unreachable")

    monkeypatch.setattr(main, "save_site", lambda s, targets: None)
    monkeypatch.setattr(main, "save_probes", flaky_save)
    written = asyncio.run(main.run(settings(), duration_s=0.1))
    assert len(calls) >= 2  # the failed round was skipped and the loop carried on
    assert written == sum(calls[1:])


def test_router_stats_stay_off_without_chr_settings():
    assert main.make_router(settings()) is None
    assert main.make_router(settings(collector_router_stats=True)) is None
