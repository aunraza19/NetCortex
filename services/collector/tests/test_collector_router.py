import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from netcortex_collector import router

T0 = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


def interfaces(rx: int, tx: int, drops: int = 0) -> list[dict]:
    # RouterOS REST returns every value as a string.
    return [
        {"name": "ether1", "rx-byte": str(rx), "tx-byte": str(tx), "rx-drop": str(drops),
         "tx-drop": "0", "rx-error": "0", "tx-error": "0"},
    ]  # fmt: skip


def queues(upload: int, download: int) -> list[dict]:
    return [
        {"name": "sub-42", "target": "10.0.0.42/32", "bytes": f"{upload}/{download}"},
        {"name": "whole-lan", "target": "10.0.0.0/24", "bytes": "1/1"},
    ]


def test_counters_are_parsed_and_subnet_queues_skipped():
    assert router.interface_counters(interfaces(100, 200, drops=3)) == {"ether1": (100, 200, 3, 0)}
    assert router.queue_counters(queues(upload=5, download=9)) == {"10.0.0.42": (9, 5)}


def test_first_poll_is_baseline_then_deltas_and_resets_are_skipped():
    tracker = router.DeltaTracker()
    assert tracker.update(T0, {"a": (100,), "b": (50,)}) == (0.0, {})
    seconds, deltas = tracker.update(T0 + timedelta(seconds=30), {"a": (400,), "b": (10,)})
    assert seconds == 30 and deltas == {"a": (300,)}  # b went down: counter reset


def test_poll_turns_byte_counters_into_bits_per_second():
    polls = iter(
        [interfaces(0, 0), queues(0, 0), interfaces(3_750_000, 375_000, drops=4), queues(75, 750)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(polls))

    stats = router.RouterStats("http://chr.invalid", "tester", "not-a-real-password", 5)
    stats._client = httpx.AsyncClient(
        base_url="http://chr.invalid", transport=httpx.MockTransport(handler)
    )

    async def two_polls():
        await stats.poll("home-lab", T0)
        return await stats.poll("home-lab", T0 + timedelta(seconds=30))

    ifaces, subscribers = asyncio.run(two_polls())
    assert (ifaces[0].iface, ifaces[0].rx_bps, ifaces[0].tx_bps, ifaces[0].drops) == (
        "ether1", 1_000_000, 100_000, 4,
    )  # fmt: skip
    assert (subscribers[0].ip, subscribers[0].rx_bps, subscribers[0].tx_bps) == (
        "10.0.0.42",
        200,
        20,
    )
