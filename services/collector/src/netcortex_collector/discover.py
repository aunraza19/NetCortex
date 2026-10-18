"""Find the gateway and the first upstream hop with the system traceroute.

icmplib's traceroute needs admin rights on Windows, so we parse `tracert -d` (Windows) or
`traceroute -n` (Linux, macOS). Only hop numbers and IPs are read, so the output language
doesn't matter.
"""

import asyncio
import logging
import re
import sys

log = logging.getLogger(__name__)

# A hop line starts with the hop number; the first IPv4 address on it is the hop.
# Lines for hops that didn't answer ("*  *  *  Request timed out.") have no address.
HOP_LINE = re.compile(r"^\s*(\d+)\s.*?\b((?:\d{1,3}\.){3}\d{1,3})\b")


def parse_hops(output: str) -> list[str]:
    """Answering hop addresses, in hop order."""
    hops = []
    for line in output.splitlines():
        match = HOP_LINE.match(line)
        if match:
            hops.append(match.group(2))
    return hops


def traceroute_command(target: str, max_hops: int) -> list[str]:
    if sys.platform == "win32":
        return ["tracert", "-d", "-h", str(max_hops), "-w", "1000", target]
    return ["traceroute", "-n", "-m", str(max_hops), "-w", "1", target]


async def discover_path(
    target: str, max_hops: int = 4, timeout_s: float = 60
) -> tuple[str | None, str | None]:
    """(gateway, first upstream hop) on the way to `target`; None where not found."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *traceroute_command(target, max_hops),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        log.warning("traceroute failed (%s); set COLLECTOR_GATEWAY/COLLECTOR_UPSTREAM_HOP", exc)
        return None, None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        log.warning("traceroute timed out; set COLLECTOR_GATEWAY/COLLECTOR_UPSTREAM_HOP")
        return None, None
    hops = parse_hops(stdout.decode(errors="replace"))
    return (hops[0] if hops else None), (hops[1] if len(hops) > 1 else None)
