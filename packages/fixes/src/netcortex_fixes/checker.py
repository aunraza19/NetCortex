"""Test a fix on the CHR test router before a human sees it, and apply it after approval.

dry_run: export -> apply -> export and diff -> roll back -> export and compare with the
original. A fix passes only if it applied cleanly, changed something, and rolled back to
exactly the original config.
"""

import difflib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from netcortex_core import FixPlan, Settings, TemplateId, db, get_settings

from netcortex_fixes.router import RouterClient, RouterError
from netcortex_fixes.templates import get_template, render, validate


@dataclass
class DryRun:
    ok: bool
    params: dict[str, Any]  # validated, including values read from the router
    commands: str
    rollback: str
    diff: list[str]  # config lines the fix added (+) or removed (-)
    log: str


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


def dry_run(template_id: TemplateId | str, params: dict[str, Any], client: RouterClient) -> DryRun:
    template_id = TemplateId(template_id)
    if template_id is TemplateId.NONE:
        return DryRun(True, {}, "", "", [], "Template none: no router change to test.")
    params = validate(template_id, params | router_params(template_id, client))
    commands, rollback = render(template_id, params)
    log = [f"Dry run of {template_id.value} on CHR at {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC"]

    before = client.export()
    try:
        log.append(client.run(commands))
        applied = True
    except RouterError as exc:
        log.append(f"APPLY FAILED: {exc}")
        applied = False
    after = client.export()
    diff = _diff(before, after)
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
        "applied cleanly": applied,
        "changed the config": bool(diff),
        "rolled back cleanly": rolled_back,
        "config restored exactly": not leftover,
    }
    log.append("; ".join(f"{name}: {'yes' if ok else 'NO'}" for name, ok in checks.items()))
    return DryRun(all(checks.values()), params, commands, rollback, diff, "\n".join(log))


def check_fix(
    incident_id: UUID,
    template_id: TemplateId | str,
    params: dict[str, Any],
    client: RouterClient | None = None,
    settings: Settings | None = None,
) -> FixPlan:
    """Dry-run a proposed fix on CHR and store the result in fix_plans."""
    client = client or RouterClient.chr(settings)
    try:
        result = dry_run(template_id, params, client)
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
        commands, rollback = render(template_id, params)
        plan = FixPlan(
            incident_id=incident_id,
            template_id=TemplateId(template_id),
            params=params,
            commands=commands,
            rollback=rollback,
            dry_run_ok=False,
            dry_run_log=f"Dry run could not run: {exc}",
        )
    with db.get_pool(settings).connection() as conn:
        db.insert_fix_plan(conn, plan)
    return plan


def _target(settings: Settings | None) -> Settings:
    settings = settings or get_settings()
    if settings.apply_target != "chr":
        raise RouterError("Only APPLY_TARGET=chr is supported; real routers are not wired up")
    return settings


def apply(
    plan: FixPlan, client: RouterClient | None = None, settings: Settings | None = None
) -> str:
    """Apply an approved, dry-run-tested fix to the CHR test router."""
    if plan.decision != "approved":
        raise RouterError("Refusing to apply a fix that has not been approved")
    if not plan.dry_run_ok:
        raise RouterError("Refusing to apply a fix that did not pass its dry run")
    client = client or RouterClient.chr(_target(settings))
    return client.run(plan.commands)


def rollback(
    plan: FixPlan, client: RouterClient | None = None, settings: Settings | None = None
) -> str:
    """Undo an applied fix on the CHR test router."""
    client = client or RouterClient.chr(_target(settings))
    return client.run(plan.rollback)
