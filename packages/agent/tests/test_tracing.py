import asyncio
import json

import pytest
import sentry_sdk
from netcortex_agent.tracing import SentryModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from sentry_sdk.transport import Transport


@pytest.fixture
def ai_spans():
    """gen_ai spans Sentry would send (as their own `span` items), kept here instead."""
    spans = []

    class Keep(Transport):
        def capture_envelope(self, envelope):
            for item in envelope.items:
                if item.type == "span":
                    spans.extend(json.loads(item.payload.get_bytes())["items"])

    sentry_sdk.init(transport=Keep(), traces_sample_rate=1.0, default_integrations=False)
    yield spans
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def test_each_model_request_is_a_gen_ai_chat_span_with_token_counts(ai_spans):
    agent = Agent(SentryModel(TestModel(), agent_name="netcortex_investigator"))

    async def model_request_activity():
        with sentry_sdk.start_transaction(op="temporal.activity", name="model_request") as tx:
            await agent.run("Why is the uplink slow?")
        return tx.span_id

    activity_span_id = asyncio.run(model_request_activity())
    [span] = ai_spans
    data = {key: value["value"] for key, value in span["attributes"].items()}
    assert span["name"] == "chat test" and span["parent_span_id"] == activity_span_id
    assert data["sentry.op"] == "gen_ai.chat" and data["gen_ai.operation.name"] == "chat"
    assert data["gen_ai.request.model"] == data["gen_ai.response.model"] == "test"
    assert data["gen_ai.agent.name"] == "netcortex_investigator"
    assert data["gen_ai.usage.input_tokens"] > 0 and data["gen_ai.usage.output_tokens"] > 0
    assert data["gen_ai.usage.total_tokens"] == (
        data["gen_ai.usage.input_tokens"] + data["gen_ai.usage.output_tokens"]
    )
