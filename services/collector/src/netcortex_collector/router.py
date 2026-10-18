"""Interface and per-subscriber traffic from the RouterOS v7 REST API.

RouterOS reports cumulative byte counters, so rates come from the difference between two
polls. The first poll only sets the baseline. A counter that went down (router reboot,
counter reset) is skipped for that poll. `drops` and `errors` are counts during the interval.
"""

from datetime import datetime

import httpx
from netcortex_core import IfaceMetric, Source, SubscriberMetric

Counters = dict[str, tuple[int, ...]]


def interface_counters(items: list[dict]) -> Counters:
    """/rest/interface -> {name: (rx_bytes, tx_bytes, drops, errors)}."""
    counters = {}
    for item in items:
        values = [
            int(item.get(field, 0))
            for field in ("rx-byte", "tx-byte", "rx-drop", "tx-drop", "rx-error", "tx-error")
        ]
        rx, tx, rx_drop, tx_drop, rx_err, tx_err = values
        counters[item["name"]] = (rx, tx, rx_drop + tx_drop, rx_err + tx_err)
    return counters


def queue_counters(items: list[dict]) -> Counters:
    """/rest/queue/simple -> {subscriber ip: (download_bytes, upload_bytes)}.

    A simple queue's `bytes` is "upload/download" seen from its target, and `target` is
    like "10.0.0.42/32". Queues that target a whole subnet are skipped.
    """
    counters = {}
    for item in items:
        target = item.get("target", "").split(",")[0]
        if not target.endswith("/32"):
            continue
        upload, download = (int(part) for part in item.get("bytes", "0/0").split("/"))
        counters[target.removesuffix("/32")] = (download, upload)
    return counters


class DeltaTracker:
    """Keeps the previous poll and returns counter differences since then."""

    def __init__(self) -> None:
        self._previous: tuple[datetime, Counters] | None = None

    def update(self, now: datetime, counters: Counters) -> tuple[float, Counters]:
        """(seconds since the last poll, deltas for keys seen in both polls).

        Empty on the first poll; keys whose counters went down are left out.
        """
        previous, self._previous = self._previous, (now, counters)
        if previous is None:
            return 0.0, {}
        then, old = previous
        seconds = (now - then).total_seconds()
        if seconds <= 0:
            return 0.0, {}
        deltas = {}
        for key, values in counters.items():
            if key not in old:
                continue
            delta = tuple(new - prev for new, prev in zip(values, old[key], strict=True))
            if all(d >= 0 for d in delta):
                deltas[key] = delta
        return seconds, deltas


class RouterStats:
    """Polls one RouterOS router over REST."""

    def __init__(self, base_url: str, username: str, password: str, timeout_s: float) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/").removesuffix("/rest"),
            auth=(username, password),
            timeout=timeout_s,
        )
        self._interfaces = DeltaTracker()
        self._queues = DeltaTracker()

    async def _get(self, path: str) -> list[dict]:
        response = await self._client.get(path)
        response.raise_for_status()
        return response.json()

    async def poll(
        self, site_id: str, now: datetime
    ) -> tuple[list[IfaceMetric], list[SubscriberMetric]]:
        iface_counters = interface_counters(await self._get("/rest/interface"))
        sub_counters = queue_counters(await self._get("/rest/queue/simple"))
        seconds, ifaces = self._interfaces.update(now, iface_counters)
        sub_seconds, subscribers = self._queues.update(now, sub_counters)

        def bps(byte_delta: int, interval_s: float) -> int:
            return round(byte_delta * 8 / interval_s)

        iface_rows = [
            IfaceMetric(
                time=now,
                site_id=site_id,
                iface=name,
                rx_bps=bps(rx, seconds),
                tx_bps=bps(tx, seconds),
                drops=drops,
                errors=errors,
                source=Source.LIVE,
            )
            for name, (rx, tx, drops, errors) in ifaces.items()
        ]
        subscriber_rows = [
            SubscriberMetric(
                time=now,
                site_id=site_id,
                ip=ip,
                rx_bps=bps(down, sub_seconds),
                tx_bps=bps(up, sub_seconds),
                source=Source.LIVE,
            )
            for ip, (down, up) in subscribers.items()
        ]
        return iface_rows, subscriber_rows

    async def close(self) -> None:
        await self._client.aclose()
