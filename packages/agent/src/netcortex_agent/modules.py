"""The detector and the injector the runtime uses.

- `detect`: the rule-based detector. It alone decides when an incident opens.
- `inject`: the scripted incident injector for the simulated site `sim-tower`.

The partner's packages (TabPFN detector, simulator, runbook search, news check) stay in the
repository as experimental code; the runtime doesn't call them.
"""

from netcortex_agent.stub_detector import detect
from netcortex_agent.stub_injector import inject

__all__ = ["detect", "inject"]
