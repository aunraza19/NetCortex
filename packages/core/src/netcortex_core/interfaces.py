"""Signatures of the module functions the workflows and the agent call.

Failure rules (the same for every module):
- detect() and search_runbook() raise ModuleUnavailable when their model, provider or data
  can't produce a real answer. An empty list from search_runbook() means "no matches".
- speak() returns b"" when voice is unavailable.
- check_news() returns NewsCheck(available=False, summary=<reason>) when it can't check.
- Every network call inside a module has a finite timeout (Settings.http_timeout_s by default).
Callers treat any of these as "skip this step"; an unavailable module never blocks an incident.
"""

import inspect
from typing import Literal, Protocol

from netcortex_core.schemas import (
    Cause,
    DetectionResult,
    IncidentReport,
    MetricsWindow,
    NewsCheck,
    RunbookChunk,
    ScenarioLabel,
)


class ModuleUnavailable(RuntimeError):
    """A module could not produce a real result. Subclass it (e.g. DetectorUnavailable)."""


class Detect(Protocol):  # packages/detector
    def __call__(
        self, site_id: str, window: MetricsWindow, history: MetricsWindow
    ) -> DetectionResult: ...


class SearchRunbook(Protocol):  # packages/runbook
    def __call__(self, query: str, k: int = 5) -> list[RunbookChunk]: ...


class Speak(Protocol):  # packages/notify; returns MP3 bytes
    def __call__(self, text: str, lang: Literal["en", "ur"]) -> bytes: ...


class CheckNews(Protocol):  # packages/notify
    def __call__(self, provider: str | None, target: str | None) -> NewsCheck: ...


class Inject(Protocol):  # packages/simgen
    def __call__(
        self, site_id: str, scenario_type: Cause, duration_min: int, seed: int | None
    ) -> ScenarioLabel: ...


class Investigate(Protocol):  # packages/agent
    async def __call__(
        self, site_id: str, detection: DetectionResult, window: MetricsWindow
    ) -> IncidentReport: ...


def conforms(func: object, protocol: type) -> bool:
    """True if `func` takes the same parameters (names, order, defaults) as the protocol.

    Use it in tests: `assert conforms(detect, Detect)`.
    """
    expected = list(inspect.signature(protocol.__call__).parameters.values())[1:]  # drop self
    actual = list(inspect.signature(func).parameters.values())  # type: ignore[arg-type]
    if [(p.name, p.kind, p.default) for p in actual] != [
        (p.name, p.kind, p.default) for p in expected
    ]:
        return False
    return inspect.iscoroutinefunction(func) == inspect.iscoroutinefunction(protocol.__call__)
