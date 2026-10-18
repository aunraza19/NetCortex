from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest
from netcortex_core import (
    PROBE_COLUMNS,
    Cause,
    DetectionResult,
    ForecastPoint,
    IncidentReport,
    IncidentStatus,
    MetricsWindow,
    NewsCheck,
    ProbeMetric,
    SeriesForecast,
    TemplateId,
    parse_series_key,
    series_key,
)
from pydantic import ValidationError

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


def test_vocabulary_matches_the_plan_exactly():
    assert [c.value for c in Cause] == [
        "uplink_congestion",
        "heavy_user",
        "upstream_degradation",
        "game_route_issue",
        "wireless_interference",
        "uplink_down",
        "dns_slow",
        "normal",
    ]
    assert [t.value for t in TemplateId] == [
        "queue_limit",
        "failover_route",
        "priority_queue",
        "dns_servers",
        "none",
    ]
    assert [s.value for s in IncidentStatus] == [
        "open",
        "awaiting_approval",
        "applying",
        "verifying",
        "resolved",
        "rolled_back",
        "rejected",
    ]


@pytest.mark.parametrize(
    ("parts", "key"),
    [
        (("probe", "8.8.8.8", "rtt_ms"), "probe:8.8.8.8:rtt_ms"),
        (("probe", "dns:1.1.1.1", "rtt_ms"), "probe:dns:1.1.1.1:rtt_ms"),
        (("iface", "ether1", "util_pct"), "iface:ether1:util_pct"),
    ],
)
def test_series_key_round_trip(parts, key):
    assert series_key(*parts) == key
    assert parse_series_key(key) == parts


def test_parse_series_key_rejects_garbage():
    with pytest.raises(ValueError):
        parse_series_key("latency:8.8.8.8:rtt_ms")


def test_metrics_window_defaults_to_empty_frames_with_columns():
    window = MetricsWindow(as_of=NOW)
    assert tuple(window.probe_metrics.columns) == PROBE_COLUMNS
    assert window.iface_metrics.empty and window.subscriber_metrics.empty


def test_metrics_window_normalises_as_of_to_utc():
    pkt = timezone(timedelta(hours=5))
    window = MetricsWindow(as_of=datetime(2026, 10, 18, 20, 0, tzinfo=pkt))
    assert window.as_of == NOW and window.as_of.tzinfo == UTC


def test_metrics_window_rejects_naive_time_and_missing_columns():
    with pytest.raises(ValidationError, match="timezone-aware"):
        MetricsWindow(as_of=datetime(2026, 10, 18))
    with pytest.raises(ValidationError, match="probe_metrics is missing columns"):
        MetricsWindow(as_of=NOW, probe_metrics=pd.DataFrame({"time": [NOW]}))


def test_metrics_window_allows_extra_columns():
    frame = pd.DataFrame(columns=[*PROBE_COLUMNS, "note"])
    assert "note" in MetricsWindow(as_of=NOW, probe_metrics=frame).probe_metrics


def test_probe_metric_allows_missing_rtt_on_total_loss_but_bounds_loss():
    row = dict(time=NOW, site_id="home-lab", target="8.8.8.8", source="live")
    assert ProbeMetric(**row, rtt_ms=None, loss_pct=100).rtt_ms is None
    with pytest.raises(ValidationError):
        ProbeMetric(**row, rtt_ms=20, loss_pct=101)


def test_forecast_quantiles_must_be_ordered():
    with pytest.raises(ValidationError, match="p10 <= p50 <= p90"):
        ForecastPoint(time=NOW, p10=5, p50=4, p90=6)


def test_detection_result_round_trips_through_json():
    detection = DetectionResult(
        is_anomaly=True,
        score=0.93,
        series=[
            SeriesForecast(
                series_key="iface:ether1:util_pct",
                points=[ForecastPoint(time=NOW, p10=60, p50=70, p90=80)],
            )
        ],
        cause_guess=Cause.UPLINK_CONGESTION,
        cause_confidence=0.8,
        evidence=["uplink ether1 at 97% for 6 min"],
        model="tabpfn-3.5",
        mode="cloud",
    )
    assert DetectionResult.model_validate_json(detection.model_dump_json()) == detection
    with pytest.raises(ValidationError):
        DetectionResult.model_validate({**detection.model_dump(), "score": 1.5})


def _report(**changes):
    report = dict(
        summary="Uplink ether1 is full; everyone's games lag.",
        likely_cause="uplink_congestion",
        confidence=0.7,
        template_id="priority_queue",
        template_params={"uplink": "ether1"},
        customer_message_en="We are fixing slow internet. Back to normal in minutes.",
        customer_message_ur="ہم سست انٹرنیٹ ٹھیک کر رہے ہیں۔",
    )
    return IncidentReport.model_validate(report | changes)


def test_incident_report_accepts_a_valid_report():
    assert _report().template_id is TemplateId.PRIORITY_QUEUE


def test_incident_report_rejects_unknown_template_and_bad_confidence():
    with pytest.raises(ValidationError):
        _report(template_id="reboot_router")
    with pytest.raises(ValidationError):
        _report(confidence=1.2)


def test_template_none_takes_no_params():
    assert _report(template_id="none", template_params={}).template_params == {}
    with pytest.raises(ValidationError, match="takes no params"):
        _report(template_id="none", template_params={"ip": "10.0.0.2"})


def test_incident_report_has_a_json_schema_for_the_agent():
    schema = IncidentReport.model_json_schema()
    assert "template_id" in schema["required"]


def test_unavailable_news_check_never_claims_an_outage():
    check = NewsCheck(available=False, summary="SerpApi key is not configured.")
    assert not check.outage_reported and check.items == []
