"""Lead tests for contract-shaped observations, independent of database setup."""

from datetime import UTC, datetime

from netcortex_core import ProbeMetric, SubscriberMetric
from netcortex_simgen.simulator import generate, generate_supplemental


def test_dns_scenario_uses_measured_lookup_probe_kind():
    probes, _, labels = generate(
        days=1,
        hours=3,
        seed=11,
        site_id="north-tower",
        scenario_type="dns_slow",
        start=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert "kind" in probes
    dns = probes[(probes.kind == "dns") & (probes.target == "dns:1.1.1.1")]
    assert not dns.empty
    label = labels[0]
    active = dns[(dns.time >= label["start"]) & (dns.time < label["end"])]
    healthy = dns[dns.time < label["start"]]
    assert not healthy.empty and active.rtt_ms.median() > healthy.rtt_ms.median()
    assert ProbeMetric.model_validate(active.iloc[0].to_dict()).kind.value == "dns"


def test_heavy_user_has_core_shaped_subscriber_observations():
    start = datetime(2026, 10, 12, tzinfo=UTC)
    _, _, labels = generate(
        days=1, hours=3, seed=12, site_id="north-tower", scenario_type="heavy_user", start=start
    )
    rows = generate_supplemental(
        labels, start=start, end=labels[0]["end"], seed=12, site_ids=["north-tower"]
    )
    # Production subscriber frame is a separate helper; supplemental remains experimental.
    import netcortex_simgen.simulator as simulator

    subscriber = simulator.generate_subscribers(
        labels, start=start, end=labels[0]["end"], seed=12, site_ids=["north-tower"]
    )
    assert not subscriber.empty and not rows.empty
    validated = [SubscriberMetric.model_validate(r) for r in subscriber.to_dict("records")]
    assert all(r.source.value == "sim" for r in validated)
    assert subscriber.time.min() < labels[0]["start"]
    assert subscriber.loc[subscriber.time >= labels[0]["start"], "tx_bps"].max() > 0
