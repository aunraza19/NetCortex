import asyncio
import json

import pytest
from netcortex_agent import agent, cases, facts
from netcortex_core import Investigate, NewsCheck, Settings, TemplateId, conforms
from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

SETTINGS = Settings(_env_file=None)  # never read the real .env
CASE = cases.heavy_user()

GOOD = {
    "summary": "Subscriber 10.0.0.42 is filling the uplink, so everyone else lags.",
    "likely_cause": "heavy_user",
    "confidence": 0.8,
    "evidence": ["ether1 at 97% for 8 min", "10.0.0.42 downloading 140 Mbit/s"],
    "template_id": "queue_limit",
    "template_params": {"target": "10.0.0.42", "upload_mbps": 5, "download_mbps": 20},
    "customer_message_en": "Internet is slow for some users. We are fixing it now.",
    "customer_message_ur": "کچھ صارفین کے لیے انٹرنیٹ سست ہے۔ ہم اسے ٹھیک کر رہے ہیں۔",
}


def run(model, case=CASE):
    with agent.incident_agent.override(model=model):
        return asyncio.run(
            agent.run_investigation(
                case.site.id, case.detection, case.window, site=case.site, settings=SETTINGS
            )
        )


def test_investigate_matches_the_shared_interface():
    assert conforms(agent.investigate, Investigate)


def test_valid_report_is_returned_with_normalised_params():
    report, stats = run(TestModel(call_tools=["get_metrics"], custom_output_args=GOOD))
    assert report.template_id is TemplateId.QUEUE_LIMIT
    assert report.template_params == {"target": "10.0.0.42", "upload_mbps": 5, "download_mbps": 20}
    assert stats.tool_calls == ["get_metrics"] and not stats.fell_back


def scripted(*outputs):
    """A model that returns each output in turn as its final answer, recording requests."""
    requests: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        requests.append(messages)
        output = outputs[min(len(requests), len(outputs)) - 1]
        tool = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool, json.dumps(output))])

    return FunctionModel(respond), requests


def test_invalid_template_gets_one_retry_with_the_error_fed_back():
    wrong = GOOD | {"template_id": "dns_servers", "template_params": {"servers": ["1.1.1.1"]}}
    model, requests = scripted(wrong, GOOD)
    report, stats = run(model)
    assert report.template_id is TemplateId.QUEUE_LIMIT
    assert stats.output_retries == 1 and not stats.fell_back
    retry = [p for p in requests[1][-1].parts if isinstance(p, RetryPromptPart)][0]
    assert "not allowed for cause 'heavy_user'" in str(retry.content)


def test_bad_params_twice_falls_back_to_template_none():
    bad = GOOD | {"template_params": {"target": "10.0.0.42; /system reboot"}}
    model, requests = scripted(bad, bad)
    report, stats = run(model)
    assert len(requests) == 2  # the first try plus exactly one retry
    assert stats.fell_back
    assert report.template_id is TemplateId.NONE and report.template_params == {}
    assert report.likely_cause is CASE.detection.cause_guess and report.confidence <= 0.3


def test_router_filled_params_are_dropped_from_the_report():
    dns = cases.dns_slow()
    output = GOOD | {
        "likely_cause": "dns_slow",
        "template_id": "dns_servers",
        "template_params": {"servers": ["1.1.1.1", "8.8.8.8"], "previous_servers": ["9.9.9.9"]},
    }
    report, _ = run(TestModel(call_tools=[], custom_output_args=output), dns)
    assert report.template_params == {"servers": ["1.1.1.1", "8.8.8.8"]}


def test_news_check_result_is_copied_into_the_report(monkeypatch):
    news = NewsCheck(available=True, outage_reported=True, summary="ISP outage reported.")
    monkeypatch.setattr(agent.modules, "check_news", lambda provider, target: news)
    output = GOOD | {
        "likely_cause": "upstream_degradation",
        "template_id": "none",
        "template_params": {},
    }
    report, stats = run(TestModel(call_tools=["check_news"], custom_output_args=output))
    assert stats.tool_calls == ["check_news"]
    assert report.upstream_check == news


def test_list_templates_offers_only_allowed_templates_and_agent_params():
    offered = agent.list_templates("dns_slow")
    assert [t["id"] for t in offered] == ["dns_servers", "none"]
    assert list(offered[0]["params"]) == ["servers"]


def test_metric_summary_reads_the_window():
    summary = facts.metric_summary(CASE.window, "subscriber:10.0.0.42:rx_bps", 5)
    assert summary["latest"] > 100_000_000 and len(summary["points"]) <= facts.MAX_POINTS
    assert "error" in facts.metric_summary(CASE.window, "probe:9.9.9.9:rtt_ms", 15)
    assert "error" in facts.metric_summary(CASE.window, "latency", 15)


def test_total_loss_is_reported_as_no_measured_values():
    summary = facts.metric_summary(cases.uplink_down().window, "probe:1.1.1.1:rtt_ms", 5)
    assert "every probe was lost" in summary["note"]


def test_prompt_lists_site_layout_and_queryable_series():
    prompt = facts.build_prompt(CASE.site.id, CASE.site, CASE.detection, CASE.window)
    assert "ether2 backup 80 Mbit/s gateway 10.20.0.1" in prompt
    assert "subscriber:<name>:{rx_bps,tx_bps} for names ['10.0.0.42'" in prompt


@pytest.mark.live
def test_live_gemma_investigates_heavy_user():
    """Needs the Mac model server (OLLAMA_BASE_URL)."""
    report, stats = asyncio.run(
        agent.run_investigation(CASE.site.id, CASE.detection, CASE.window, site=CASE.site)
    )
    assert stats.tool_calls, "Gemma should call at least one tool"
    assert report.template_id in {TemplateId.QUEUE_LIMIT, TemplateId.NONE}
