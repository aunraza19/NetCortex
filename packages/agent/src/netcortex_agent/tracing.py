"""Sentry `gen_ai.chat` spans for the agent's model requests.

Sentry's Pydantic AI integration hooks the agent's graph. Under Temporal that graph runs
inside the workflow sandbox, so the integration records nothing. The model request itself
runs in a `model_request` activity, so wrapping the model puts one span per Gemma request
inside that activity's transaction, with the attributes Sentry's AI Agents view reads
(https://docs.sentry.io/platforms/python/agent-tracing/manual-instrumentation/).
"""

from typing import Any

import sentry_sdk
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.wrapper import WrapperModel
from sentry_sdk.consts import OP, SPANDATA


class SentryModel(WrapperModel):
    """A model that reports each request as a span: model, token counts and latency."""

    def __init__(self, wrapped: Any, agent_name: str):
        super().__init__(wrapped)
        self.agent_name = agent_name

    async def request(self, messages, model_settings, model_request_parameters) -> ModelResponse:
        with sentry_sdk.start_span(op=OP.GEN_AI_CHAT, name=f"chat {self.model_name}") as span:
            span.set_data(SPANDATA.GEN_AI_OPERATION_NAME, "chat")
            span.set_data(SPANDATA.GEN_AI_PROVIDER_NAME, self.system)
            span.set_data(SPANDATA.GEN_AI_SYSTEM, self.system)  # older name, still read
            span.set_data(SPANDATA.GEN_AI_REQUEST_MODEL, self.model_name)
            span.set_data(SPANDATA.GEN_AI_AGENT_NAME, self.agent_name)
            response = await super().request(messages, model_settings, model_request_parameters)
            usage = response.usage
            span.set_data(SPANDATA.GEN_AI_RESPONSE_MODEL, response.model_name or self.model_name)
            span.set_data(SPANDATA.GEN_AI_USAGE_INPUT_TOKENS, usage.input_tokens)
            span.set_data(SPANDATA.GEN_AI_USAGE_OUTPUT_TOKENS, usage.output_tokens)
            span.set_data(SPANDATA.GEN_AI_USAGE_TOTAL_TOKENS, usage.total_tokens)
            if response.finish_reason:
                span.set_data(SPANDATA.GEN_AI_RESPONSE_FINISH_REASONS, [response.finish_reason])
            if response.tool_calls:  # names only; arguments can hold subscriber IPs
                span.set_data(
                    SPANDATA.GEN_AI_RESPONSE_TOOL_CALLS,
                    [call.tool_name for call in response.tool_calls],
                )
        return response
