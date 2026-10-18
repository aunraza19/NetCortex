"""Ping and DNS probes. Each returns one RTT in ms per attempt, or None for a lost attempt."""

import asyncio
import statistics
import time

import dns.asyncresolver
import dns.exception
import dns.resolver
from icmplib import async_ping


def summarize(rtts: list[float | None]) -> tuple[float | None, float | None, float]:
    """(average RTT, jitter = standard deviation of RTTs, loss %) for one burst."""
    received = [rtt for rtt in rtts if rtt is not None]
    loss_pct = 100.0 * (len(rtts) - len(received)) / len(rtts)
    if not received:
        return None, None, loss_pct
    return statistics.fmean(received), statistics.pstdev(received), loss_pct


async def ping_rtts(host: str, count: int, timeout_s: float) -> list[float | None]:
    """A burst of `count` ICMP echoes. Works without admin rights (unprivileged sockets)."""
    result = await async_ping(host, count=count, interval=0.2, timeout=timeout_s, privileged=False)
    rtts: list[float | None] = list(result.rtts)
    return rtts + [None] * (count - len(rtts))


async def dns_rtts(resolver_ip: str, name: str, count: int, timeout_s: float) -> list[float | None]:
    """`count` concurrent A lookups of `name` sent straight to one resolver, timed in ms."""
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = [resolver_ip]
    resolver.lifetime = timeout_s

    async def lookup() -> float | None:
        start = time.perf_counter()
        try:
            await resolver.resolve(name, "A")
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            pass  # the resolver answered; that is still a lookup time
        except dns.exception.DNSException:  # timeout, SERVFAIL, refused
            return None
        return (time.perf_counter() - start) * 1000

    return list(await asyncio.gather(*(lookup() for _ in range(count))))
