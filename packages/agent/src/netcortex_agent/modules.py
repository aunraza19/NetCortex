"""Workstream B functions the agent and worker call, and which implementation each uses.

- `detect`: always our rule-based stand-in. Rules decide when an incident opens.
- `tabpfn_detect`: the partner's TabPFN detector, as a second opinion once an incident is
  open. Usable only after `configure_tabpfn()` succeeded (it needs a training artifact).
- `inject`: the partner's simulator for the sites it knows; `sim-tower` (laid out like the
  CHR baseline) and unknown sites use our stand-in.
- `search_runbook`, `check_news`: the partner's when installed, stubs otherwise.
"""

import logging
from pathlib import Path

from netcortex_core import Cause, DetectionResult, MetricsWindow, ScenarioLabel

from netcortex_agent import stub_injector
from netcortex_agent.stubs import detect

try:
    from netcortex_runbook import search_runbook
except ImportError:
    from netcortex_agent.stubs import search_runbook

try:
    from netcortex_notify import check_news
except ImportError:
    from netcortex_agent.stubs import check_news

try:
    import netcortex_detector as _detector
except ImportError:
    _detector = None

try:
    import netcortex_simgen as _simgen
except ImportError:
    _simgen = None

__all__ = ["check_news", "detect", "inject", "search_runbook", "tabpfn_detect"]

log = logging.getLogger(__name__)
_tabpfn_ready = False


def configure_tabpfn(artifact: Path) -> bool:
    """Fit the partner's detector from its training artifact. Slow (minutes on cloud)."""
    global _tabpfn_ready
    if _detector is None:
        log.info("TabPFN second opinion off: netcortex_detector is not installed")
        return False
    try:
        _detector.configure_detector(artifact)
    except Exception as exc:  # the live path never depends on it
        log.warning("TabPFN second opinion off: %s: %s", type(exc).__name__, exc)
        return False
    _tabpfn_ready = True
    log.info("TabPFN second opinion ready")
    return True


def tabpfn_ready() -> bool:
    return _tabpfn_ready


def tabpfn_detect(
    site_id: str, window: MetricsWindow, history: MetricsWindow
) -> DetectionResult | None:
    """The partner's detection, or None if it isn't configured."""
    if not _tabpfn_ready:
        return None
    return _detector.detect(site_id, window, history)


def _simgen_sites() -> set[str]:
    if _simgen is None:
        return set()
    return {site["id"] for site in _simgen.sites()["sites"]}


def inject(
    site_id: str, scenario_type: Cause, duration_min: int, seed: int | None
) -> ScenarioLabel:
    if site_id != stub_injector.SIM_SITE.id and site_id in _simgen_sites():
        return _simgen.inject(site_id, scenario_type, duration_min, seed)
    return stub_injector.inject(site_id, scenario_type, duration_min, seed)
