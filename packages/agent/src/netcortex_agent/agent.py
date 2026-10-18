"""The incident investigator: a Pydantic AI agent on local Gemma (Ollama, OpenAI-compatible).

The model reads the detection, checks metrics through tools, picks one fix template allowed
for the cause and fills its params. It never writes router commands: an output validator
rejects any template or param the fix templates don't allow, the error goes back to the
model once, and a second failure falls back to template `none`.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import netcortex_fixes as fixes
from netcortex_core import (
    Cause,
    DetectionResult,
    IncidentReport,
    MetricsWindow,
    ModuleUnavailable,
    NewsCheck,
    Settings,
    Site,
    TemplateId,
    db,
    get_settings,
)
from pydantic_ai import Agent, ModelRetry, RunContext, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.ollama import OllamaProvider

from netcortex_agent import facts, modules

log = logging.getLogger(__name__)

MODEL_TIMEOUT_S = 180  # one model request; a full report on a 4B model can take a while
PARTNER_TIMEOUT_S = 15  # runbook search and news check

INSTRUCTIONS = """\
You investigate network incidents for a small internet provider that runs MikroTik routers.

Work in this order:
1. Check the evidence with get_metrics (and get_forecast) on the key series.
2. Decide the likely cause. Causes: uplink_congestion, heavy_user, upstream_degradation,
   game_route_issue, wireless_interference, uplink_down, dns_slow, normal.
3. Call list_templates with that cause. Pick template_id only from its result.
4. For upstream_degradation or game_route_issue, call check_news.
5. Return the incident report.

Rules:
- template_params must match the chosen template's params exactly: names, types, limits.
  Use the site's real interfaces, gateways and IP addresses from the prompt and metrics.
- Never write router commands.
- If the evidence is unclear, use template none and a confidence below 0.4.
- summary: 1-2 plain sentences for the network owner.
- evidence: short facts with numbers, e.g. "ether1 at 97% for 6 min".
- customer_message_en: under 25 words, plain English, no jargon.
- customer_message_ur: the same message in Urdu script.
"""

FALLBACK_EN = "We are looking into a network problem and will update you soon."
FALLBACK_UR = "ہم نیٹ ورک کے ایک مسئلے کو دیکھ رہے ہیں اور جلد آپ کو آگاہ کریں گے۔"


@dataclass
class Deps:
    site_id: str
    detection: DetectionResult
    window: MetricsWindow
    site: Site | None = None
    news: NewsCheck | None = None  # last check_news result, copied into the report


@dataclass
class RunStats:
    """How a run went, for logs, traces and the thinking comparison."""

    seconds: float = 0.0
    tool_calls: list[str] = field(default_factory=list)
    output_retries: int = 0
    retry_reasons: list[str] = field(default_factory=list)  # what the model was told to fix
    fell_back: bool = False


incident_agent = Agent(
    deps_type=Deps,
    output_type=IncidentReport,
    instructions=INSTRUCTIONS,
    retries={"tools": 2, "output": 1},
)


@incident_agent.tool
def get_metrics(ctx: RunContext[Deps], series: str, minutes: int = 15) -> dict[str, Any]:
    """Recent values of one series, e.g. 'probe:8.8.8.8:rtt_ms', 'iface:ether1:util_pct'
    or 'subscriber:10.0.0.42:rx_bps'. Returns latest, mean, min, max and up to 10 points."""
    return facts.metric_summary(ctx.deps.window, series, minutes)


@incident_agent.tool
def get_forecast(ctx: RunContext[Deps], series: str) -> dict[str, Any]:
    """The detector's p10/p50/p90 forecast for one series, 1-5 minutes ahead."""
    return facts.forecast_summary(ctx.deps.detection, series)


@incident_agent.tool_plain
def list_templates(cause: Cause) -> list[dict[str, Any]]:
    """Fix templates allowed for a cause, with their params. `none` is always allowed."""
    return [
        {
            "id": template.id.value,
            "description": template.description,
            "params": {name: spec.describe() for name, spec in template.agent_params().items()},
        }
        for template in fixes.templates_for(cause)
    ]


@incident_agent.tool_plain
async def search_runbook(query: str) -> list[dict[str, Any]] | str:
    """Search MikroTik RouterOS documentation. Returns the top 3 passages."""
    try:
        chunks = await asyncio.wait_for(
            asyncio.to_thread(modules.search_runbook, query, 3), PARTNER_TIMEOUT_S
        )
    except (ModuleUnavailable, TimeoutError) as exc:
        return f"runbook search unavailable ({type(exc).__name__})"
    return [
        chunk.model_dump(include={"title", "section", "text", "source_url"}) for chunk in chunks
    ]


@incident_agent.tool
async def check_news(
    ctx: RunContext[Deps], provider: str | None = None, target: str | None = None
) -> dict[str, Any]:
    """Search recent news for an outage at the upstream provider or a game server."""
    try:
        news = await asyncio.wait_for(
            asyncio.to_thread(modules.check_news, provider, target), PARTNER_TIMEOUT_S
        )
    except (ModuleUnavailable, TimeoutError) as exc:
        news = NewsCheck(available=False, summary=f"Outage check failed ({type(exc).__name__}).")
    ctx.deps.news = news
    return news.model_dump(mode="json")


@incident_agent.output_validator
def check_fix(ctx: RunContext[Deps], report: IncidentReport) -> IncidentReport:
    """Only templates allowed for the cause, with params that pass the template schema."""
    allowed = [t.id for t in fixes.templates_for(report.likely_cause)]
    if report.template_id not in allowed:
        raise ModelRetry(
            f"template_id {report.template_id.value!r} is not allowed for cause "
            f"{report.likely_cause.value!r}. Allowed: {[t.value for t in allowed]}."
        )
    agent_params = fixes.get_template(report.template_id).agent_params()
    params = {k: v for k, v in report.template_params.items() if k in agent_params}
    observed = None
    if report.template_id is TemplateId.QUEUE_LIMIT and "target" in params:
        try:
            observed = facts.subscriber_rates(ctx.deps.window, str(params["target"]))
        except ValueError:
            observed = None  # not an IP; the schema check below reports it
    try:
        clean = fixes.validate(report.template_id, params, observed)
    except fixes.ParamError as exc:
        schema = {name: spec.describe() for name, spec in agent_params.items()}
        raise ModelRetry(
            f"template_params are invalid: {exc}. {report.template_id.value} needs exactly "
            f"these params: {schema}. Keep template_id {report.template_id.value!r} and the "
            "rest of the report; correct only template_params."
        ) from exc
    return report.model_copy(
        update={"template_params": {k: v for k, v in clean.items() if k in agent_params}}
    )


def build_model(settings: Settings) -> OpenAIChatModel:
    base_url = settings.ollama_base_url.rstrip("/") + "/v1"
    return OpenAIChatModel(settings.agent_model, provider=OllamaProvider(base_url=base_url))


def model_settings(thinking: bool) -> OpenAIChatModelSettings:
    settings = OpenAIChatModelSettings(temperature=0.2, timeout=MODEL_TIMEOUT_S)
    if not thinking:
        # Gemma thinks by default; Ollama's OpenAI API turns it off with reasoning_effort=none.
        settings["openai_reasoning_effort"] = "none"  # type: ignore[typeddict-item]
    return settings


def fallback_report(detection: DetectionResult) -> IncidentReport:
    """Notify-only report when the model can't produce a valid one."""
    return IncidentReport(
        summary=(
            "Automatic investigation could not choose a safe fix. The detector suggests "
            f"{detection.cause_guess.value} ({detection.cause_confidence:.0%}); please check."
        ),
        likely_cause=detection.cause_guess,
        confidence=min(detection.cause_confidence, 0.3),
        evidence=detection.evidence[:5],
        template_id=TemplateId.NONE,
        customer_message_en=FALLBACK_EN,
        customer_message_ur=FALLBACK_UR,
    )


def load_site(site_id: str) -> Site | None:
    """The site's layout from the database, or None if it isn't available."""
    try:
        with db.get_pool().connection() as conn:
            return db.fetch_site(conn, site_id)
    except Exception as exc:
        log.warning("site %s layout unavailable: %s", site_id, type(exc).__name__)
        return None


def _stats(messages: list[ModelMessage], started: float) -> RunStats:
    stats = RunStats(seconds=round(time.perf_counter() - started, 1))
    for message in messages:
        for part in message.parts:
            if isinstance(message, ModelResponse) and isinstance(part, ToolCallPart):
                if part.tool_name != "final_result":
                    stats.tool_calls.append(part.tool_name)
            elif isinstance(part, RetryPromptPart) and part.tool_name in (None, "final_result"):
                stats.output_retries += 1
                stats.retry_reasons.append(str(part.content)[:300])
    return stats


async def run_investigation(
    site_id: str,
    detection: DetectionResult,
    window: MetricsWindow,
    *,
    site: Site | None = None,
    thinking: bool = False,
    settings: Settings | None = None,
) -> tuple[IncidentReport, RunStats]:
    """investigate() plus run statistics; lets callers pass the site and thinking mode."""
    settings = settings or get_settings()
    deps = Deps(site_id, detection, window, site=site)
    prompt = facts.build_prompt(site_id, site, detection, window)
    started = time.perf_counter()
    with capture_run_messages() as messages:
        try:
            result = await incident_agent.run(
                prompt,
                deps=deps,
                model=build_model(settings),
                model_settings=model_settings(thinking),
            )
        except UnexpectedModelBehavior as exc:
            log.warning("agent output failed validation twice, using template none: %s", exc)
            stats = _stats(messages, started)
            stats.fell_back = True
            return fallback_report(detection), stats
    report = result.output
    if report.upstream_check is None and deps.news is not None:
        report = report.model_copy(update={"upstream_check": deps.news})
    return report, _stats(result.all_messages(), started)


async def investigate(
    site_id: str, detection: DetectionResult, window: MetricsWindow
) -> IncidentReport:
    """Investigate one detection. Connection errors propagate so Temporal can retry."""
    site = await asyncio.to_thread(load_site, site_id)
    report, stats = await run_investigation(site_id, detection, window, site=site)
    log.info(
        "investigated %s in %.1fs: %s -> %s (tools %s, retries %d, fallback %s)",
        site_id, stats.seconds, report.likely_cause.value, report.template_id.value,
        stats.tool_calls, stats.output_retries, stats.fell_back,
    )  # fmt: skip
    return report
