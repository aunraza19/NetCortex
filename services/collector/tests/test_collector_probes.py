import asyncio

import dns.exception
import dns.resolver
import pytest
from netcortex_collector import probes


def test_summarize_full_burst():
    rtt, jitter, loss = probes.summarize([10.0, 12.0, 14.0, 12.0, 12.0])
    assert rtt == pytest.approx(12.0)
    assert jitter == pytest.approx(1.2649, rel=1e-3)
    assert loss == 0.0


def test_summarize_partial_and_total_loss():
    assert probes.summarize([10.0, None, 20.0, None, None]) == (15.0, 5.0, 60.0)
    assert probes.summarize([None] * 5) == (None, None, 100.0)


class FakeHost:
    def __init__(self, rtts):
        self.rtts = rtts


def test_ping_pads_lost_echoes_with_none(monkeypatch):
    async def fake_ping(host, count, interval, timeout, privileged):
        assert privileged is False  # must work without admin rights
        return FakeHost([5.0, 6.0, 7.0])

    monkeypatch.setattr(probes, "async_ping", fake_ping)
    assert asyncio.run(probes.ping_rtts("1.1.1.1", 5, 1.0)) == [5.0, 6.0, 7.0, None, None]


def test_dns_counts_answers_and_nxdomain_but_not_timeouts(monkeypatch):
    outcomes = iter([None, dns.resolver.NXDOMAIN(), dns.exception.Timeout(), None])

    async def fake_resolve(self, name, rdtype):
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(probes.dns.asyncresolver.Resolver, "resolve", fake_resolve)
    rtts = asyncio.run(probes.dns_rtts("1.1.1.1", "google.com", 4, 2.0))
    assert [rtt is None for rtt in rtts] == [False, False, True, False]
