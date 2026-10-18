"""Stand-ins for Workstream B modules that haven't merged yet. Same interfaces as
netcortex_core.interfaces, so `modules.py` can switch to the real ones automatically.
"""

from netcortex_core import NewsCheck, RunbookChunk

from netcortex_agent.stub_detector import detect
from netcortex_agent.stub_injector import inject

__all__ = ["check_news", "detect", "inject", "search_runbook"]

# A few short pointers into the RouterOS docs, keyed by topic, until packages/runbook lands.
_RUNBOOK = {
    ("queue", "limit", "bandwidth", "subscriber", "heavy"): RunbookChunk(
        title="Queues: simple queues",
        section="Simple queue",
        text="A simple queue limits traffic for one target IP or subnet. max-limit is "
        "upload/download. Queues are checked top to bottom; the first match wins.",
        source_url="https://help.mikrotik.com/docs/ (stub)",
        score=0.5,
    ),
    ("failover", "route", "gateway", "backup", "uplink", "down"): RunbookChunk(
        title="IP routing: default route failover",
        section="check-gateway",
        text="Add a second default route with a higher distance. check-gateway=ping makes "
        "the router disable a route whose gateway stops answering, so traffic moves to the "
        "backup.",
        source_url="https://help.mikrotik.com/docs/ (stub)",
        score=0.5,
    ),
    ("dns", "resolver", "lookup"): RunbookChunk(
        title="DNS",
        section="Servers",
        text="/ip dns set servers=... sets upstream resolvers. Flush the cache after changing "
        "them with /ip dns cache flush.",
        source_url="https://help.mikrotik.com/docs/ (stub)",
        score=0.5,
    ),
    ("priority", "congestion", "mangle", "game", "latency"): RunbookChunk(
        title="Queues: queue tree with packet marks",
        section="Priority",
        text="Mark DNS and game packets in mangle, then give their queue tree a lower priority "
        "number (1 is highest) under a parent queue limited below the uplink's capacity.",
        source_url="https://help.mikrotik.com/docs/ (stub)",
        score=0.5,
    ),
}


def search_runbook(query: str, k: int = 5) -> list[RunbookChunk]:
    words = query.lower()
    hits = [chunk for keys, chunk in _RUNBOOK.items() if any(key in words for key in keys)]
    return hits[:k]


def check_news(provider: str | None, target: str | None) -> NewsCheck:
    return NewsCheck(available=False, summary="Outage news check is not connected yet (stub).")
