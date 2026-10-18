"""Test a fix on the CHR test router before a human sees it, and apply it after approval.

dry_run: export -> apply -> export and diff -> roll back -> export and compare with the
original. A fix passes only if it applied cleanly, changed something, and rolled back to
exactly the original config.

Every object a fix creates is named after its incident (tag nc-1a2b3c4d), and rollbacks
target only those names. If an apply fails partway, only what it created is undone; config
that existed before is never removed or changed.
"""

import difflib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from netcortex_core import FixPlan, Settings, TemplateId, db, get_settings

from netcortex_fixes.router import RouterClient, RouterError
from netcortex_fixes.templates import TEST_TAG, get_template, render, tag_for, validate


@dataclass
class DryRun:
    ok: bool
    params: dict[str, Any]  # validated, including values read from the router
    commands: str
    rollback: str
    diff: list[str]  # config lines the fix added (+) or removed (-)
    log: str  # ends with "Result: passed" or "Result: FAILED: <reason>"
    reason: str = ""  # why it failed; empty if it passed


class ApplyFailed(RouterError):
    """A fix could not be applied. The message says what was (or wasn't) undone."""


def router_params(template_id: TemplateId, client: RouterClient) -> dict[str, Any]:
    """Params the template takes from the router itself (set_by: router)."""
    wanted = {
        name for name, spec in get_template(template_id).params.items() if spec.set_by == "router"
    }
    values: dict[str, Any] = {}
    if "previous_servers" in wanted:
        servers = client.get("/ip/dns").get("servers", "")
        values["previous_servers"] = [s for s in servers.split(",") if s]
    return values


def _diff(before: list[str], after: list[str]) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(before, after, lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def _apply(client: RouterClient, commands: str, rollback: str, tag: str) -> str:
    """Run a fix's commands. On failure, undo only what they created, then raise ApplyFailed."""
    before = client.export()
    if tag in commands and any(tag in line for line in before):
        raise ApplyFailed(f"objects named {tag}-* already exist on the router; nothing changed")
    try:
        return client.run(commands)
    except RouterError as exc:
        reason = str(exc)
    if not _diff(before, client.export()):
        raise ApplyFailed(f"{reason}; nothing was applied, so nothing was rolled back")
    try:  # partly applied: the rollback targets only this fix's own (tagged) objects
        client.run(rollback)
    except RouterError as exc:
        raise ApplyFailed(f"{reason}; undoing the partial change also failed: {exc}") from exc
    leftover = _diff(before, client.export())
    if leftover:
        raise ApplyFailed(f"{reason}; partial change NOT fully undone: {'; '.join(leftover)}")
    raise ApplyFailed(f"{reason}; the partial change was rolled back")


def dry_run(
    template_id: TemplateId | str,
    params: dict[str, Any],
    client: RouterClient,
    tag: str = TEST_TAG,
) -> DryRun:
    template_id = TemplateId(template_id)
    if template_id is TemplateId.NONE:
        return DryRun(True, {}, "", "", [], "Template none: no router change to test.")
    params = validate(template_id, params | router_params(template_id, client))
    commands, rollback = render(template_id, params, tag)
    log = [f"Dry run of {template_id.value} on CHR at {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC"]

    def result(diff: list[str], reason: str) -> DryRun:
        log.append(f"Result: FAILED: {reason}" if reason else "Result: passed")
        return DryRun(not reason, params, commands, rollback, diff, "\n".join(log), reason)

    before = client.export()
    try:
        log.append(_apply(client, commands, rollback, tag))
    except ApplyFailed as exc:
        log.append(f"APPLY FAILED: {exc}")
        return result([], f"apply failed: {exc}")
    diff = _diff(before, client.export())
    log.append("Config change:\n" + ("\n".join(diff) or "(none)"))

    try:
        log.append(client.run(rollback))
        rolled_back = True
    except RouterError as exc:
        log.append(f"ROLLBACK FAILED: {exc}")
        rolled_back = False
    leftover = _diff(before, client.export())
    if leftover:
        log.append("NOT RESTORED, differences from the original:\n" + "\n".join(leftover))

    checks = {
        "changed the config": bool(diff),
        "rolled back cleanly": rolled_back,
        "restored the config exactly": not leftover,
    }
    log.append("; ".join(f"{name}: {'yes' if ok else 'NO'}" for name, ok in checks.items()))
    return result(diff, ", ".join(f"not {name}" for name, ok in checks.items() if not ok))


def check_fix(
    incident_id: UUID,
    template_id: TemplateId | str,
    params: dict[str, Any],
    client: RouterClient | None = None,
    settings: Settings | None = None,
) -> FixPlan:
    """Dry-run a proposed fix on CHR and store the result in fix_plans."""
    client = client or RouterClient.chr(settings)
    tag = tag_for(incident_id)
    try:
        result = dry_run(template_id, params, client, tag)
        plan = FixPlan(
            incident_id=incident_id,
            template_id=TemplateId(template_id),
            params=result.params,
            commands=result.commands,
            rollback=result.rollback,
            dry_run_ok=result.ok,
            dry_run_log=result.log,
        )
    except RouterError as exc:  # CHR down: the plan is stored as not tested
        commands, rollback = render(template_id, params, tag)
        plan = FixPlan(
            incident_id=incident_id,
            template_id=TemplateId(template_id),
            params=params,
            commands=commands,
            rollback=rollback,
            dry_run_ok=False,
            dry_run_log=f"Dry run could not run: {exc}\nResult: FAILED: CHR unreachable",
        )
    with db.get_pool(settings).connection() as conn:
        db.insert_fix_plan(conn, plan)
    return plan


def failure_reason(plan: FixPlan) -> str:
    """The reason line a failed dry run ends with, for status notes and events."""
    last = plan.dry_run_log.strip().splitlines()[-1] if plan.dry_run_log.strip() else ""
    return last.removeprefix("Result: FAILED: ") if last.startswith("Result: FAILED") else ""


def _target(settings: Settings | None) -> Settings:
    settings = settings or get_settings()
    if settings.apply_target != "chr":
        raise RouterError("Only APPLY_TARGET=chr is supported; real routers are not wired up")
    return settings


def apply(
    plan: FixPlan, client: RouterClient | None = None, settings: Settings | None = None
) -> str:
    """Apply an approved, dry-run-tested fix to the CHR test router.

    Raises ApplyFailed if it can't; only what this fix created is undone.
    """
    if plan.decision != "approved":
        raise RouterError("Refusing to apply a fix that has not been approved")
    if not plan.dry_run_ok:
        raise RouterError("Refusing to apply a fix that did not pass its dry run")
    client = client or RouterClient.chr(_target(settings))
    return _apply(client, plan.commands, plan.rollback, tag_for(plan.incident_id))


def rollback(
    plan: FixPlan, client: RouterClient | None = None, settings: Settings | None = None
) -> str:
    """Undo an applied fix on the CHR test router (it removes only this incident's objects)."""
    client = client or RouterClient.chr(_target(settings))
    return client.run(plan.rollback)
