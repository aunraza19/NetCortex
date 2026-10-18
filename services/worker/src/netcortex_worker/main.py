"""`uv run worker`: the Temporal worker, plus one MonitorSiteWorkflow per MONITOR_SITES site.

Sentry: every activity runs in a transaction, in a scope of its own. Activities of incident
workflows share one trace whose ID is the incident ID, so a whole incident (model calls,
tool calls, dry run, apply, verify) shows up as a single trace.
"""

import argparse
import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any
from uuid import UUID

import netcortex_fixes as fixes
import sentry_sdk
from netcortex_core import get_settings
from netcortex_core.tracing import init_sentry
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
    Worker,
)
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from netcortex_worker import activities
from netcortex_worker.workflows import IncidentWorkflow, MonitorInput, MonitorSiteWorkflow, Timing

log = logging.getLogger("worker")

# Modules the workflow sandbox may share with the worker process instead of re-importing.
PASSTHROUGH = (
    "netcortex_core", "netcortex_agent", "netcortex_fixes", "pandas", "numpy", "sentry_sdk",
    "openai", "psycopg", "psycopg_pool", "yaml", "jinja2", "markupsafe", "dateutil", "tzdata",
)  # fmt: skip


def trace_id_for(workflow_id: str) -> str | None:
    """incident-<uuid> -> the uuid's 32 hex digits, used as the Sentry trace ID."""
    if not workflow_id.startswith("incident-"):
        return None
    try:
        return UUID(workflow_id.removeprefix("incident-")).hex
    except ValueError:
        return None


async def run_traced(
    workflow_id: str, activity_type: str, call: Callable[[], Awaitable[Any]]
) -> Any:
    """Run one activity in a Sentry transaction with a scope of its own.

    Activities run concurrently on one event loop. Sharing a scope, a span from one activity
    (say the home-lab monitor's detect) would land in whichever transaction started last.
    """
    trace_id = trace_id_for(workflow_id)
    headers = {"sentry-trace": f"{trace_id}-{secrets.token_hex(8)}-1"} if trace_id else {}
    with sentry_sdk.isolation_scope():
        transaction = sentry_sdk.continue_trace(headers, op="temporal.activity", name=activity_type)
        with sentry_sdk.start_transaction(transaction):
            sentry_sdk.set_tag("workflow_id", workflow_id)
            sentry_sdk.set_tag("activity", activity_type)
            return await call()


class _SentryActivities(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        info = activity.info()
        return await run_traced(
            info.workflow_id, info.activity_type, lambda: self.next.execute_activity(input)
        )


class SentryInterceptor(Interceptor):
    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _SentryActivities(next)


async def start_monitors(client: Client, sites: list[str], timing: Timing, queue: str) -> None:
    for site_id in sites:
        await client.start_workflow(
            MonitorSiteWorkflow.run,
            MonitorInput(site_id=site_id, timing=timing),
            id=f"monitor-{site_id}",
            task_queue=queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        log.info("monitoring %s", site_id)


async def run() -> None:
    settings = get_settings()
    init_sentry("worker", settings)
    fixes.load_templates()  # read the YAML once, outside the workflow sandbox
    client = await Client.connect(settings.temporal_address, plugins=[PydanticAIPlugin()])
    timing = Timing(
        monitor_interval_s=settings.monitor_interval_s,
        approval_timeout_s=settings.approval_timeout_s,
        verify_wait_s=settings.verify_wait_s,
    )
    runner = SandboxedWorkflowRunner()
    runner = replace(
        runner, restrictions=SandboxRestrictions.default.with_passthrough_modules(*PASSTHROUGH)
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[MonitorSiteWorkflow, IncidentWorkflow],
        activities=activities.ALL,
        workflow_runner=runner,
        interceptors=[SentryInterceptor()],
    )
    await start_monitors(client, settings.monitor_sites, timing, settings.temporal_task_queue)
    log.info("worker running on task queue %s", settings.temporal_task_queue)
    await worker.run()


def main() -> int:
    argparse.ArgumentParser(prog="worker", description=__doc__.splitlines()[0]).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
