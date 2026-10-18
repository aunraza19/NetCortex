"""RouterOS fix templates: the only source of router commands."""

from netcortex_fixes.checker import DryRun, apply, check_fix, dry_run, rollback
from netcortex_fixes.errors import ParamError
from netcortex_fixes.router import RouterClient, RouterError
from netcortex_fixes.templates import (
    NONE_TEMPLATE,
    ParamSpec,
    Template,
    get_template,
    load_templates,
    render,
    templates_for,
    validate,
)

__all__ = [
    "DryRun",
    "RouterClient",
    "RouterError",
    "apply",
    "check_fix",
    "dry_run",
    "rollback",
    "NONE_TEMPLATE",
    "ParamError",
    "ParamSpec",
    "Template",
    "get_template",
    "load_templates",
    "render",
    "templates_for",
    "validate",
]
