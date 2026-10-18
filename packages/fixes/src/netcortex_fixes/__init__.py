"""RouterOS fix templates: the only source of router commands."""

from netcortex_fixes.errors import ParamError
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
