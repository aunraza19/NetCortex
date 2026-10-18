"""Fix templates: load the YAML files, validate parameters, render RouterOS commands.

Router commands only ever come from these templates. A parameter value that doesn't fit
its schema is rejected before rendering, so nothing the model writes reaches the router
except values that passed validation (IPs, bounded ints, strict regexes).
"""

import ipaddress
import re
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from netcortex_core import Cause, TemplateId
from pydantic import BaseModel

from netcortex_fixes.checks import CHECKS, Observed
from netcortex_fixes.errors import ParamError

TEMPLATES_DIR = Path(__file__).resolve().parents[4] / "templates" / "routeros"

ParamType = Literal["int", "str", "enum", "ipv4", "ipv4_or_cidr", "ipv4_list"]


class ParamSpec(BaseModel):
    type: ParamType
    description: str
    min: int | None = None
    max: int | None = None
    regex: str | None = None
    values: list[str] | None = None  # for enum
    min_items: int = 1
    max_items: int = 8
    default: Any = None
    set_by: Literal["agent", "router"] = "agent"  # router: filled in by the fix checker

    def describe(self) -> dict[str, Any]:
        """The schema as the agent sees it: only the constraints that apply to this type."""
        described = self.model_dump(exclude_none=True, exclude={"set_by", "min_items", "max_items"})
        if self.type == "ipv4_list":
            described |= {"min_items": self.min_items, "max_items": self.max_items}
        return described

    def check(self, name: str, value: Any) -> Any:
        """Return the value normalised, or raise ParamError."""
        match self.type:
            case "int":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ParamError(f"{name} must be an integer")
                if (self.min is not None and value < self.min) or (
                    self.max is not None and value > self.max
                ):
                    raise ParamError(f"{name} must be between {self.min} and {self.max}")
                return value
            case "str":
                if not isinstance(value, str) or not re.fullmatch(self.regex or ".*", value):
                    raise ParamError(f"{name} must match {self.regex}")
                return value
            case "enum":
                if value not in (self.values or []):
                    raise ParamError(f"{name} must be one of {self.values}")
                return value
            case "ipv4":
                return str(_ipv4(name, value))
            case "ipv4_or_cidr":
                if isinstance(value, str) and "/" in value:
                    try:
                        return str(ipaddress.IPv4Network(value, strict=True))
                    except ValueError as exc:
                        raise ParamError(f"{name} must be an IPv4 address or subnet") from exc
                return str(_ipv4(name, value))
            case "ipv4_list":
                if not isinstance(value, list):
                    raise ParamError(f"{name} must be a list of IPv4 addresses")
                if not self.min_items <= len(value) <= self.max_items:
                    raise ParamError(
                        f"{name} must have {self.min_items} to {self.max_items} addresses"
                    )
                return [str(_ipv4(name, item)) for item in value]


def _ipv4(name: str, value: Any) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError, TypeError) as exc:
        raise ParamError(f"{name} must be an IPv4 address, got {value!r}") from exc


class Verify(BaseModel):
    metric: Literal["rtt_ms", "jitter_ms", "loss_pct", "util_pct"]
    goal: Literal["decrease", "increase"]
    by_pct: float


class Template(BaseModel):
    id: TemplateId
    description: str
    status: str = "untested on CHR"
    allowed_causes: list[Cause]
    params: dict[str, ParamSpec] = {}
    apply: str = ""
    rollback: str = ""
    verify: Verify | None = None
    checks: list[str] = []  # names in netcortex_fixes.checks.CHECKS

    def agent_params(self) -> dict[str, ParamSpec]:
        """Parameters the agent fills in (router-filled ones are left out)."""
        return {name: spec for name, spec in self.params.items() if spec.set_by == "agent"}


NONE_TEMPLATE = Template(
    id=TemplateId.NONE,
    description="No router change; notify the owner (and send a technician if needed).",
    status="built-in",
    allowed_causes=list(Cause),
)

_jinja = SandboxedEnvironment(
    undefined=StrictUndefined, autoescape=False, keep_trailing_newline=False
)


@cache
def load_templates(directory: Path = TEMPLATES_DIR) -> dict[TemplateId, Template]:
    """Every template by id, including the built-in `none`."""
    templates = {TemplateId.NONE: NONE_TEMPLATE}
    for path in sorted(directory.glob("*.yaml")):
        template = Template.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if path.stem != template.id.value:
            raise ValueError(f"{path.name} declares id {template.id.value!r}")
        unknown = set(template.checks) - set(CHECKS)
        if unknown:
            raise ValueError(f"{path.name} names unknown checks: {sorted(unknown)}")
        templates[template.id] = template
    return templates


def get_template(template_id: TemplateId | str) -> Template:
    return load_templates()[TemplateId(template_id)]


def templates_for(cause: Cause | str) -> list[Template]:
    """Templates allowed for a cause; `none` is always last."""
    cause = Cause(cause)
    allowed = [
        t
        for t in load_templates().values()
        if t.id != TemplateId.NONE and cause in t.allowed_causes
    ]
    return [*allowed, NONE_TEMPLATE]


def validate(
    template_id: TemplateId | str, params: dict[str, Any], observed: Observed | None = None
) -> dict[str, Any]:
    """Check params against the template's schema and fill defaults. Raises ParamError.

    With `observed` (current network values, e.g. the subscriber's rate), the template's
    checks run too.
    """
    template = get_template(template_id)
    unknown = set(params) - set(template.params)
    if unknown:
        raise ParamError(f"unknown params for {template.id.value}: {sorted(unknown)}")
    clean = {}
    for name, spec in template.params.items():
        if name in params:
            clean[name] = spec.check(name, params[name])
        elif spec.default is not None:
            clean[name] = spec.default
        else:
            raise ParamError(f"missing param {name!r} for {template.id.value}")
    if observed is not None:
        for check in template.checks:
            CHECKS[check](clean, observed)
    return clean


def render(template_id: TemplateId | str, params: dict[str, Any]) -> tuple[str, str]:
    """(apply commands, rollback commands) for validated params."""
    template = get_template(template_id)
    clean = validate(template.id, params)
    apply = _jinja.from_string(template.apply).render(**clean).strip()
    rollback = _jinja.from_string(template.rollback).render(**clean).strip()
    return apply, rollback
