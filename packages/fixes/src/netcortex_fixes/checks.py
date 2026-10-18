"""Checks that compare a template's params with what the network is doing right now.

A template lists its checks by name (`checks:` in the YAML). They run after the schema
check, and only when the caller passes observations, e.g. the agent's output validator
with the subscriber's current traffic. Error messages say what value would pass, so the
model can fix its answer on the retry.
"""

import math
from collections.abc import Callable
from typing import Any

from netcortex_fixes.errors import ParamError

CAP_FRACTION = 0.5  # a cap must be at most half the subscriber's current rate
MIN_HEAVY_MBPS = 2.0  # below this the subscriber isn't heavy and a cap won't help

Observed = dict[str, float]


def cap_below_current_rate(params: dict[str, Any], observed: Observed) -> None:
    """queue_limit: the cap must bite in the subscriber's busier direction.

    Needs observed `current_download_mbps` and/or `current_upload_mbps` for the target.
    """
    down = observed.get("current_download_mbps")
    up = observed.get("current_upload_mbps")
    if down is None and up is None:
        return  # nothing observed for this target; the schema check still applies
    direction = "download" if (down or 0.0) >= (up or 0.0) else "upload"
    current = down if direction == "download" else up
    target = params["target"]
    if current < MIN_HEAVY_MBPS:
        raise ParamError(
            f"{target} only uses {current:.1f} Mbit/s, so limiting it won't help; "
            "check the subscriber series for the heavy user or choose another template"
        )
    cap = params[f"{direction}_mbps"]
    allowed = max(1, math.floor(current * CAP_FRACTION))
    if cap > current * CAP_FRACTION:
        raise ParamError(
            f"{direction}_mbps={cap} is not clearly below {target}'s current {direction} rate "
            f"of {current:.0f} Mbit/s, so it would not limit anything. Set {direction}_mbps "
            f"to at most {allowed} ({CAP_FRACTION:.0%} of the current rate)"
        )


CHECKS: dict[str, Callable[[dict[str, Any], Observed], None]] = {
    "cap_below_current_rate": cap_below_current_rate,
}
