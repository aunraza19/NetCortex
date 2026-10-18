"""The incident agent wrapped for Temporal: each model request and tool call is an activity,
so a worker crash mid-investigation resumes where it stopped instead of starting over."""

from datetime import timedelta

from netcortex_agent.agent import MODEL_TIMEOUT_S, build_model, incident_agent, model_settings
from netcortex_core import get_settings
from pydantic_ai.durable_exec.temporal import TemporalAgent
from temporalio.common import RetryPolicy
from temporalio.workflow import ActivityConfig

# The wrapped agent must have a model of its own; TemporalAgent turns calls to it into
# activities. (Outside the worker, run_investigation passes its model explicitly.)
incident_agent.model = build_model(get_settings())

temporal_agent = TemporalAgent(
    incident_agent,
    activity_config=ActivityConfig(
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=RetryPolicy(maximum_attempts=3),
    ),
    model_activity_config=ActivityConfig(
        start_to_close_timeout=timedelta(seconds=MODEL_TIMEOUT_S + 30),
        retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
    ),
)

AGENT_SETTINGS = model_settings(thinking=False)
