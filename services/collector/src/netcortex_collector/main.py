"""`uv run collector`: probe the home-lab network every 10 s and write source=live rows.

Each round pings every ICMP target and times DNS lookups against each resolver, a burst of
COLLECTOR_PINGS per target, all targets at once. A failed probe is skipped; a failed round
is logged and skipped; the loop keeps going.
"""

import argparse
import asyncio
import logging
import time
from datetime import UTC, datetime

from netcortex_core import (
    ProbeKind,
    ProbeMetric,
    ProbeTarget,
    Settings,
    Site,
    Source,
    TargetRole,
    db,
    get_settings,
)

from netcortex_collector.discover import discover_path
from netcortex_collector.probes import dns_rtts, ping_rtts, summarize
from netcortex_collector.router import RouterStats

log = logging.getLogger("collector")


def build_targets(
    settings: Settings, gateway: str | None, upstream: str | None
) -> list[ProbeTarget]:
    targets = []
    if gateway:
        targets.append(ProbeTarget(key=gateway, host=gateway, role=TargetRole.GATEWAY))
    if upstream:
        targets.append(ProbeTarget(key=upstream, host=upstream, role=TargetRole.UPSTREAM_HOP))
    for host in settings.collector_public_targets:
        targets.append(ProbeTarget(key=host, host=host, role=TargetRole.PUBLIC_DNS))
    if settings.collector_game_server:
        host = settings.collector_game_server
        targets.append(ProbeTarget(key=host, host=host, role=TargetRole.GAME_SERVER))
    for host in settings.collector_dns_resolvers:
        targets.append(
            ProbeTarget(
                key=f"dns:{host}", host=host, kind=ProbeKind.DNS, role=TargetRole.PUBLIC_DNS
            )
        )
    return targets


async def probe(target: ProbeTarget, settings: Settings, now: datetime) -> ProbeMetric | None:
    """One burst against one target, or None if the probe itself failed."""
    try:
        if target.kind is ProbeKind.DNS:
            rtts = await dns_rtts(
                target.host,
                settings.collector_dns_query,
                settings.collector_pings,
                settings.collector_dns_timeout_s,
            )
        else:
            rtts = await ping_rtts(
                target.host, settings.collector_pings, settings.collector_ping_timeout_s
            )
    except Exception as exc:  # one bad target must not sink the round
        log.warning("probe %s failed: %s: %s", target.key, type(exc).__name__, exc)
        return None
    rtt_ms, jitter_ms, loss_pct = summarize(rtts)
    return ProbeMetric(
        time=now,
        site_id=settings.site_id_live,
        target=target.key,
        kind=target.kind,
        rtt_ms=rtt_ms,
        jitter_ms=jitter_ms,
        loss_pct=loss_pct,
        source=Source.LIVE,
    )


async def probe_round(targets: list[ProbeTarget], settings: Settings) -> list[ProbeMetric]:
    now = datetime.now(UTC)
    rows = await asyncio.gather(*(probe(target, settings, now) for target in targets))
    return [row for row in rows if row is not None]


def save_site(settings: Settings, targets: list[ProbeTarget]) -> None:
    site = Site(id=settings.site_id_live, name="Home lab (live collector)", targets=targets)
    with db.get_pool(settings).connection() as conn:
        db.upsert_site(conn, site)


def save_probes(settings: Settings, rows: list[ProbeMetric]) -> None:
    with db.get_pool(settings).connection() as conn:
        db.insert_probe_metrics(conn, rows)


def save_router(settings: Settings, ifaces: list, subscribers: list) -> None:
    with db.get_pool(settings).connection() as conn:
        db.insert_iface_metrics(conn, ifaces)
        db.insert_subscriber_metrics(conn, subscribers)


def make_router(settings: Settings) -> RouterStats | None:
    if not settings.collector_router_stats:
        return None
    if not (settings.chr_rest_url and settings.chr_username and settings.chr_password):
        log.warning("COLLECTOR_ROUTER_STATS is on but CHR_REST_URL/USERNAME/PASSWORD are missing")
        return None
    return RouterStats(
        settings.chr_rest_url,
        settings.chr_username,
        settings.chr_password.get_secret_value(),
        settings.http_timeout_s,
    )


async def run(settings: Settings, duration_s: float | None = None, dry_run: bool = False) -> int:
    """Collect until stopped (or for `duration_s`). Returns the number of probe rows written."""
    gateway, upstream = settings.collector_gateway, settings.collector_upstream_hop
    if not (gateway and upstream):
        found_gateway, found_upstream = await discover_path(settings.collector_public_targets[0])
        gateway, upstream = gateway or found_gateway, upstream or found_upstream
    if not settings.collector_game_server:
        log.warning("COLLECTOR_GAME_SERVER is not set; no game server target this run")
    targets = build_targets(settings, gateway, upstream)
    log.info("targets: %s", ", ".join(f"{t.key} ({t.role.value})" for t in targets))

    if not dry_run:
        try:
            await asyncio.to_thread(save_site, settings, targets)
        except Exception as exc:
            log.warning("could not save site targets: %s", type(exc).__name__)

    router = make_router(settings)
    written = 0
    started = time.monotonic()
    next_router_poll = started
    try:
        while duration_s is None or time.monotonic() - started < duration_s:
            round_start = time.monotonic()
            # DB errors can name the database host, so only their type is logged.
            try:
                rows = await probe_round(targets, settings)
                if dry_run:
                    for row in rows:
                        log.info("%s", row.model_dump(exclude={"time", "site_id", "source"}))
                else:
                    await asyncio.to_thread(save_probes, settings, rows)
                    written += len(rows)
                log.info("round: %d/%d targets", len(rows), len(targets))
            except Exception as exc:
                log.error("round skipped: %s", type(exc).__name__)

            if router and round_start >= next_router_poll:
                next_router_poll = round_start + settings.collector_router_interval_s
                try:
                    ifaces, subscribers = await router.poll(
                        settings.site_id_live, datetime.now(UTC)
                    )
                    if not dry_run:
                        await asyncio.to_thread(save_router, settings, ifaces, subscribers)
                    log.info("router: %d interfaces, %d subscribers", len(ifaces), len(subscribers))
                except Exception as exc:
                    log.error("router poll skipped: %s", type(exc).__name__)

            elapsed = time.monotonic() - round_start
            await asyncio.sleep(max(0.0, settings.collector_interval_s - elapsed))
    finally:
        if router:
            await router.close()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collector", description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    parser.add_argument("--dry-run", action="store_true", help="print rows; don't touch the DB")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = get_settings()
    try:
        written = asyncio.run(run(settings, args.duration, args.dry_run))
    except KeyboardInterrupt:
        written = None
    finally:
        db.close_pool()
    if written is not None and not args.dry_run:
        log.info("done: %d probe rows written", written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
