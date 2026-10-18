import random
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from netcortex_agent import stub_injector
from netcortex_agent.stub_detector import detect
from netcortex_core import (
    IFACE_COLUMNS,
    PROBE_COLUMNS,
    SUBSCRIBER_COLUMNS,
    Cause,
    Detect,
    Inject,
    MetricsWindow,
    conforms,
)

AS_OF = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


def window_for(cause: Cause | None, incident_min: int = 4) -> MetricsWindow:
    """30 minutes from the injector's generator: normal, then `incident_min` of `cause`."""
    rng = random.Random(7)
    start, split = AS_OF - timedelta(minutes=30), AS_OF - timedelta(minutes=incident_min)
    parts = [
        stub_injector._rows(start, split, None, rng),
        stub_injector._rows(split, AS_OF, cause, rng),
    ]
    frames = []
    for i, columns in enumerate((PROBE_COLUMNS, IFACE_COLUMNS, SUBSCRIBER_COLUMNS)):
        rows = [row.model_dump() for part in parts for row in part[i]]
        frames.append(pd.DataFrame(rows, columns=list(columns)))
    return MetricsWindow(
        as_of=AS_OF, probe_metrics=frames[0], iface_metrics=frames[1], subscriber_metrics=frames[2]
    )


def test_stand_ins_match_the_shared_interfaces():
    assert conforms(detect, Detect)
    assert conforms(stub_injector.inject, Inject)


@pytest.mark.parametrize(
    ("cause", "evidence"),
    [
        (Cause.HEAVY_USER, "subscriber 10.0.0.42 downloading"),
        (Cause.UPLINK_DOWN, "100% loss to 1.1.1.1, 8.8.8.8 in the last minute"),
        (Cause.DNS_SLOW, "DNS lookups via 192.0.2.53"),
    ],
)
def test_detector_names_each_injected_scenario(cause, evidence):
    result = detect("sim-tower", window_for(cause), MetricsWindow(as_of=AS_OF))
    assert result.is_anomaly and result.cause_guess is cause and result.mode == "mock"
    assert any(evidence in line for line in result.evidence), result.evidence
    assert result.series and len(result.series[0].points) == 5


def test_normal_data_is_not_an_anomaly():
    result = detect("sim-tower", window_for(None), MetricsWindow(as_of=AS_OF))
    assert not result.is_anomaly and result.cause_guess is Cause.NORMAL


def test_detector_series_match_the_fix_templates_verify_metric():
    keys = {
        cause: [
            s.series_key
            for s in detect("sim-tower", window_for(cause), MetricsWindow(as_of=AS_OF)).series
        ]
        for cause in (Cause.HEAVY_USER, Cause.UPLINK_DOWN, Cause.DNS_SLOW)
    }
    assert any(k.endswith(":rtt_ms") for k in keys[Cause.HEAVY_USER])
    assert keys[Cause.UPLINK_DOWN][0].endswith(":loss_pct")
    assert keys[Cause.DNS_SLOW][0] == "probe:dns:192.0.2.53:rtt_ms"


def test_injector_rejects_unknown_sites_and_scenarios():
    with pytest.raises(ValueError, match="only knows site"):
        stub_injector.inject("north-tower", Cause.HEAVY_USER, 5, 1)
    with pytest.raises(ValueError, match="supports"):
        stub_injector.inject("sim-tower", Cause.WIRELESS_INTERFERENCE, 5, 1)


def test_an_outage_is_not_mistaken_for_slow_dns_in_its_first_minutes():
    # Found end to end: 90 s into an outage the 3-minute averages still looked like DNS
    # trouble, because DNS probes fail along with everything else.
    for minutes in (1, 2):
        result = detect("sim-tower", window_for(Cause.UPLINK_DOWN, incident_min=minutes),
                        MetricsWindow(as_of=AS_OF))  # fmt: skip
        assert result.cause_guess is Cause.UPLINK_DOWN, (minutes, result.evidence)
