"""Minimal stand-in for packages/simgen's inject() until it merges. Same interface:
inject(site_id, scenario_type, duration_min, seed) -> ScenarioLabel.

It writes source=sim rows for the sim site `sim-tower`, whose layout mirrors the CHR
baseline (gateways, subscriber IPs, DNS resolver), so fixes chosen for it apply to CHR:
- 30 minutes of normal data before now (if the site has none yet),
- the incident from now for `duration_min`,
- normal data again for RECOVERY_MIN after that.
Rows dated in the future appear to the monitor as time passes. The recovery is scripted:
CHR carries no real traffic, so a fix there can't change these numbers.
"""

import random
from datetime import UTC, datetime, timedelta

from netcortex_core import (
    Cause,
    IfaceMetric,
    ProbeKind,
    ProbeMetric,
    ProbeTarget,
    ScenarioLabel,
    Site,
    Source,
    SubscriberMetric,
    TargetRole,
    TemplateId,
    Uplink,
    UplinkRole,
    db,
)

SIM_SITE = Site(
    id="sim-tower",
    name="Sim Tower (simulated)",
    subscribers=3,
    uplinks=[
        Uplink(iface="ether1", role=UplinkRole.PRIMARY, capacity_mbps=180, gateway="10.0.2.2"),
        Uplink(iface="ether2", role=UplinkRole.BACKUP, capacity_mbps=80, gateway="192.0.2.1"),
    ],
    targets=[
        ProbeTarget(key="10.0.0.1", host="10.0.0.1", role=TargetRole.GATEWAY),
        ProbeTarget(key="1.1.1.1", host="1.1.1.1", role=TargetRole.PUBLIC_DNS),
        ProbeTarget(key="8.8.8.8", host="8.8.8.8", role=TargetRole.PUBLIC_DNS),
        ProbeTarget(
            key="dns:192.0.2.53", host="192.0.2.53", kind=ProbeKind.DNS, role=TargetRole.PUBLIC_DNS
        ),
        ProbeTarget(
            key="dns:1.1.1.1", host="1.1.1.1", kind=ProbeKind.DNS, role=TargetRole.PUBLIC_DNS
        ),
    ],
)

NORMAL_RTT = {
    "10.0.0.1": 2.0,
    "1.1.1.1": 18.0,
    "8.8.8.8": 25.0,
    "dns:192.0.2.53": 22.0,
    "dns:1.1.1.1": 12.0,
}
NORMAL_MBPS = {"10.0.0.42": 4.0, "10.0.0.57": 3.0, "10.0.0.63": 2.5}
CAPACITY_MBPS = {"ether1": 180, "ether2": 80}
BACKFILL_MIN, RECOVERY_MIN = 30, 20

EXPECTED = {
    Cause.HEAVY_USER: (TemplateId.QUEUE_LIMIT, {"target": "10.0.0.42"}, {"ip": "10.0.0.42"}),
    Cause.UPLINK_DOWN: (
        TemplateId.FAILOVER_ROUTE,
        {"primary_gateway": "10.0.2.2", "backup_gateway": "192.0.2.1"},
        {"iface": "ether1"},
    ),
    Cause.DNS_SLOW: (TemplateId.DNS_SERVERS, {}, {"resolver": "192.0.2.53"}),
}


def _rows(start: datetime, end: datetime, cause: Cause | None, rng: random.Random):
    """Probe rows every 10 s, interface and subscriber rows every 30 s."""
    probes, ifaces, subs = [], [], []
    time = start
    while time < end:
        for target, rtt in NORMAL_RTT.items():
            value, loss = rtt * rng.uniform(0.9, 1.15), 0.0
            public = not target.startswith(("10.", "dns:192."))
            if cause is Cause.HEAVY_USER and public and not target.startswith("dns:"):
                value *= 5.5
            elif cause is Cause.UPLINK_DOWN and public:
                value, loss = None, 100.0
            elif cause is Cause.DNS_SLOW and target == "dns:192.0.2.53":
                value, loss = 650 * rng.uniform(0.9, 1.1), 20.0
            probes.append(ProbeMetric(
                time=time, site_id=SIM_SITE.id, target=target,
                kind=ProbeKind.DNS if target.startswith("dns:") else ProbeKind.ICMP,
                rtt_ms=value, jitter_ms=None if value is None else value * 0.08,
                loss_pct=loss, source=Source.SIM,
            ))  # fmt: skip
        if time.second % 30 == 0:
            mbps = dict(NORMAL_MBPS)
            if cause is Cause.HEAVY_USER:
                mbps["10.0.0.42"] = 140.0
            for ip, rate in mbps.items():
                rx = rate * rng.uniform(0.9, 1.1) * 1e6
                subs.append(SubscriberMetric(
                    time=time, site_id=SIM_SITE.id, ip=ip, rx_bps=int(rx), tx_bps=int(rx / 10),
                    source=Source.SIM,
                ))  # fmt: skip
            primary = sum(mbps.values()) + 90  # plus everyone not on a per-IP queue
            if cause is Cause.UPLINK_DOWN:
                primary = 0.0
            for iface, rate in (("ether1", min(primary, 178)), ("ether2", 0.5)):
                bps = int(rate * rng.uniform(0.97, 1.0) * 1e6)
                ifaces.append(IfaceMetric(
                    time=time, site_id=SIM_SITE.id, iface=iface, rx_bps=bps, tx_bps=bps // 8,
                    util_pct=100 * bps / (CAPACITY_MBPS[iface] * 1e6), source=Source.SIM,
                ))  # fmt: skip
        time += timedelta(seconds=10)
    return probes, ifaces, subs


def inject(
    site_id: str, scenario_type: Cause, duration_min: int, seed: int | None
) -> ScenarioLabel:
    scenario_type = Cause(scenario_type)
    if site_id != SIM_SITE.id:
        raise ValueError(f"the stand-in injector only knows site {SIM_SITE.id!r}")
    if scenario_type not in EXPECTED:
        raise ValueError(f"the stand-in injector supports {[c.value for c in EXPECTED]}")
    if not 1 <= duration_min <= 60:
        raise ValueError("duration_min must be between 1 and 60")
    rng = random.Random(seed)
    now = datetime.now(UTC).replace(microsecond=0)
    now -= timedelta(seconds=now.second % 10)
    incident_end = now + timedelta(minutes=duration_min)
    template, params, affected = EXPECTED[scenario_type]
    label = ScenarioLabel(
        site_id=SIM_SITE.id, scenario_type=scenario_type, start_at=now, end_at=incident_end,
        affected=affected, expected_cause=scenario_type, expected_template=template,
        expected_params=params, seed=seed, source=Source.SIM,
    )  # fmt: skip

    with db.get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(time) FROM probe_metrics WHERE site_id = %s AND source = 'sim'",
                (SIM_SITE.id,),
            )
            last = cur.fetchone()[0]
            cur.execute(
                "SELECT 1 FROM scenario_labels WHERE site_id = %s AND end_at > %s",
                (SIM_SITE.id, now),
            )
            if cur.fetchone():
                raise ValueError(f"an injected scenario is still running on {SIM_SITE.id}")
        db.upsert_site(conn, SIM_SITE)
        # Normal data up to now (only what's missing), the incident, then recovery.
        start = (
            max(last + timedelta(seconds=10), now - timedelta(minutes=BACKFILL_MIN))
            if last
            else now - timedelta(minutes=BACKFILL_MIN)
        )
        if last and last > now:  # earlier recovery rows reach into the future: replace them
            with conn.cursor() as cur:
                for table in ("probe_metrics", "iface_metrics", "subscriber_metrics"):
                    cur.execute(
                        f"DELETE FROM {table} WHERE site_id = %s AND time >= %s", (SIM_SITE.id, now)
                    )
            start = now
        for begin, end, cause in (
            (start, now, None),
            (now, incident_end, scenario_type),
            (incident_end, incident_end + timedelta(minutes=RECOVERY_MIN), None),
        ):
            if begin >= end:
                continue
            probes, ifaces, subs = _rows(begin, end, cause, rng)
            db.insert_probe_metrics(conn, probes)
            db.insert_iface_metrics(conn, ifaces)
            db.insert_subscriber_metrics(conn, subs)
        db.insert_scenario_label(conn, label)
    return label
