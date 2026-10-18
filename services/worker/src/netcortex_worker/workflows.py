"""MonitorSiteWorkflow (one per site) and IncidentWorkflow (one per incident).

Incident flow: TabPFN second opinion (optional) -> investigate (TemporalAgent) -> dry run
on CHR -> awaiting_approval -> approve/reject signal (or time out) -> apply on CHR -> watch
-> verify -> resolved, or roll back -> rolled_back. A failed partner or model call never
kills a workflow: the incident goes on without it, or falls back to a notify-only report.
"""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from netcortex_agent import facts
    from netcortex_agent.agent import Deps, fallback_report, with_news
    from netcortex_core import DetectionResult, FixPlan, IncidentReport, IncidentStatus, TemplateId
    from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow

    from netcortex_worker import activities as act
    from netcortex_worker.durable import AGENT_SETTINGS, temporal_agent

RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
SHORT = timedelta(seconds=60)
SECOND_OPINION_TIMEOUT = timedelta(seconds=150)  # TabPFN cloud took ~115 s in Gate 2


class Timing(BaseModel):
    monitor_interval_s: float = 60
    approval_timeout_s: float = 7200
    verify_wait_s: float = 300


class MonitorInput(BaseModel):
    site_id: str
    timing: Timing = Timing()
    rounds_before_continue: int = 60


class IncidentInput(BaseModel):
    incident_id: UUID
    site_id: str
    opened_at: datetime
    prompt: str
    deps: Deps
    timing: Timing = Timing()


@workflow.defn
class MonitorSiteWorkflow:
    @workflow.run
    async def run(self, inp: MonitorInput) -> None:
        for _ in range(inp.rounds_before_continue):
            try:
                result = await workflow.execute_activity(
                    act.monitor_site,
                    inp.site_id,
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except ActivityError as exc:
                workflow.logger.warning("monitor round failed for %s: %s", inp.site_id, exc)
                result = None
            if result is not None and result.status == "opened":
                await workflow.start_child_workflow(
                    IncidentWorkflow.run,
                    IncidentInput(
                        incident_id=result.incident_id,
                        site_id=inp.site_id,
                        opened_at=result.opened_at,
                        prompt=result.prompt,
                        deps=result.deps,
                        timing=inp.timing,
                    ),
                    id=f"incident-{result.incident_id}",
                    parent_close_policy=ParentClosePolicy.ABANDON,
                )
            await workflow.sleep(timedelta(seconds=inp.timing.monitor_interval_s))
        workflow.continue_as_new(inp)


@workflow.defn
class IncidentWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = [temporal_agent]

    def __init__(self) -> None:
        self.status = IncidentStatus.OPEN
        self.decision: str | None = None
        self.decided_by = ""

    @workflow.signal
    def approve(self, decided_by: str) -> None:
        if self.status is IncidentStatus.AWAITING_APPROVAL and self.decision is None:
            self.decision, self.decided_by = "approved", decided_by

    @workflow.signal
    def reject(self, decided_by: str) -> None:
        if self.status is IncidentStatus.AWAITING_APPROVAL and self.decision is None:
            self.decision, self.decided_by = "rejected", decided_by

    @workflow.query
    def current_status(self) -> str:
        return self.status.value

    async def _status(self, inp: IncidentInput, status: IncidentStatus, note: str = "") -> None:
        self.status = status
        await workflow.execute_activity(
            act.set_status,
            args=[inp.incident_id, inp.site_id, status, note],
            start_to_close_timeout=SHORT,
            retry_policy=RETRY,
        )

    async def _second_opinion(self, inp: IncidentInput) -> DetectionResult | None:
        try:
            return await workflow.execute_activity(
                act.second_opinion,
                args=[inp.incident_id, inp.site_id, inp.opened_at],
                start_to_close_timeout=SECOND_OPINION_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError as exc:  # timed out or failed: investigate without it
            workflow.logger.warning("TabPFN second opinion skipped: %s", exc)
            return None

    async def _investigate(
        self, inp: IncidentInput, tabpfn: DetectionResult | None
    ) -> IncidentReport:
        prompt, deps = inp.prompt, inp.deps
        if tabpfn is not None:
            prompt = f"{prompt}\n{facts.second_opinion_prompt(tabpfn)}"
            deps = deps.model_copy(update={"tabpfn": tabpfn})
        try:
            result = await temporal_agent.run(prompt, deps=deps, model_settings=AGENT_SETTINGS)
            return with_news(result.output, result.all_messages())
        except Exception as exc:  # model down or invalid twice: notify-only report
            workflow.logger.warning("investigation failed, using template none: %s", exc)
            return fallback_report(inp.deps.detection)

    @workflow.run
    async def run(self, inp: IncidentInput) -> str:
        # 1. Investigate, with TabPFN's second opinion as extra evidence if it answers.
        tabpfn = await self._second_opinion(inp)
        report = await self._investigate(inp, tabpfn)
        if tabpfn is not None:
            evidence = [*report.evidence, facts.second_opinion_evidence(tabpfn)]
            report = report.model_copy(update={"evidence": evidence})
        await workflow.execute_activity(
            act.save_report,
            args=[inp.incident_id, inp.site_id, report],
            start_to_close_timeout=SHORT,
            retry_policy=RETRY,
        )

        # 2. Dry-run the fix on CHR.
        plan: FixPlan | None = None
        if report.template_id is not TemplateId.NONE:
            try:
                plan = await workflow.execute_activity(
                    act.check_fix,
                    args=[inp.incident_id, inp.site_id, report.template_id, report.template_params],
                    start_to_close_timeout=timedelta(seconds=180),
                    retry_policy=RETRY,
                )
            except ActivityError as exc:
                workflow.logger.warning("dry run could not run: %s", exc)
            if plan is None or not plan.dry_run_ok:
                await self._status(inp, IncidentStatus.REJECTED, "fix did not pass its CHR dry run")
                return self.status.value

        # 3. Wait for the owner.
        await self._status(inp, IncidentStatus.AWAITING_APPROVAL)
        try:
            await workflow.wait_condition(
                lambda: self.decision is not None,
                timeout=timedelta(seconds=inp.timing.approval_timeout_s),
            )
        except TimeoutError:
            self.decision, self.decided_by = "rejected", "timeout"
        if plan is not None:
            await workflow.execute_activity(
                act.record_decision,
                args=[plan.id, self.decision, self.decided_by],
                start_to_close_timeout=SHORT,
                retry_policy=RETRY,
            )
        if self.decision != "approved":
            await self._status(inp, IncidentStatus.REJECTED, f"rejected by {self.decided_by}")
            return self.status.value
        if plan is None:
            await self._status(inp, IncidentStatus.RESOLVED, "acknowledged; no router change")
            return self.status.value

        # 4. Apply, watch, verify.
        approved = plan.model_copy(update={"decision": "approved", "decided_by": self.decided_by})
        await self._status(inp, IncidentStatus.APPLYING)
        try:
            await workflow.execute_activity(
                act.apply_fix,
                args=[approved, inp.site_id],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError as exc:
            await self._rollback(inp, approved, f"apply failed: {exc.cause or exc}")
            return self.status.value
        await self._status(
            inp, IncidentStatus.VERIFYING, f"watching for {inp.timing.verify_wait_s:.0f} s"
        )
        await workflow.sleep(timedelta(seconds=inp.timing.verify_wait_s))
        verdict = await workflow.execute_activity(
            act.verify_fix,
            args=[inp.site_id, inp.deps.detection, report.template_id, inp.opened_at],
            start_to_close_timeout=SHORT,
            retry_policy=RETRY,
        )
        if verdict.improved:
            await self._status(inp, IncidentStatus.RESOLVED, verdict.detail)
        else:
            await self._rollback(inp, approved, f"not improved: {verdict.detail}")
        return self.status.value

    async def _rollback(self, inp: IncidentInput, plan: FixPlan, reason: str) -> None:
        try:
            await workflow.execute_activity(
                act.rollback_fix,
                plan,
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RETRY,
            )
        except ActivityError as exc:
            reason += f"; rollback failed: {exc.cause or exc}"
        await self._status(inp, IncidentStatus.ROLLED_BACK, reason)
