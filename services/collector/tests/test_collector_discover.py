import asyncio

from netcortex_collector import discover

WINDOWS_TRACERT = """
Tracing route to 1.1.1.1 over a maximum of 4 hops

  1     1 ms    <1 ms     1 ms  192.168.1.1
  2     *        *        *     Request timed out.
  3     7 ms     7 ms    17 ms  203.0.113.9
  4     4 ms     5 ms     8 ms  10.15.19.117

Trace complete.
"""

LINUX_TRACEROUTE = """traceroute to 1.1.1.1 (1.1.1.1), 4 hops max, 60 byte packets
 1  192.168.1.1  0.512 ms  0.488 ms  0.471 ms
 2  198.51.100.1  6.981 ms  7.002 ms  7.120 ms
 3  * * *
"""


def test_parse_windows_tracert_skips_silent_hops():
    assert discover.parse_hops(WINDOWS_TRACERT) == ["192.168.1.1", "203.0.113.9", "10.15.19.117"]


def test_parse_linux_traceroute():
    assert discover.parse_hops(LINUX_TRACEROUTE) == ["192.168.1.1", "198.51.100.1"]


class FakeProcess:
    async def communicate(self):
        return WINDOWS_TRACERT.encode(), b""

    def kill(self):
        pass


def test_discover_path_returns_gateway_and_first_upstream_hop(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(discover.asyncio, "create_subprocess_exec", fake_exec)
    assert asyncio.run(discover.discover_path("1.1.1.1")) == ("192.168.1.1", "203.0.113.9")


def test_discover_path_survives_a_missing_traceroute(monkeypatch):
    async def missing(*args, **kwargs):
        raise FileNotFoundError("tracert")

    monkeypatch.setattr(discover.asyncio, "create_subprocess_exec", missing)
    assert asyncio.run(discover.discover_path("1.1.1.1")) == (None, None)
