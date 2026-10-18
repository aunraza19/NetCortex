"""Workstream B functions the agent calls: the real ones once installed, stubs until then."""

try:
    from netcortex_runbook import search_runbook
except ImportError:
    from netcortex_agent.stubs import search_runbook

try:
    from netcortex_notify import check_news
except ImportError:
    from netcortex_agent.stubs import check_news

try:
    from netcortex_detector import detect
except ImportError:
    from netcortex_agent.stubs import detect

try:
    from netcortex_simgen import inject
except ImportError:
    from netcortex_agent.stubs import inject

__all__ = ["check_news", "detect", "inject", "search_runbook"]
