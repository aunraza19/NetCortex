from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


def normal_site_days(intervals: Iterable[tuple[str, Any, Any]]) -> float:
    """Return unioned normal observation exposure in site-days, merging per site."""
    by_site: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    for site_id, start, end in intervals:
        left, right = pd.Timestamp(start), pd.Timestamp(end)
        if left.tzinfo is None or right.tzinfo is None:
            raise ValueError("normal exposure intervals must be timezone-aware")
        left, right = left.tz_convert("UTC"), right.tz_convert("UTC")
        if right < left:
            raise ValueError("normal exposure interval ends before it starts")
        by_site[site_id].append((left, right))
    total_seconds = 0.0
    for site_intervals in by_site.values():
        merged = []
        for start, end in sorted(site_intervals):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        total_seconds += sum((end - start).total_seconds() for start, end in merged)
    return float(total_seconds / 86400)


def calibrate_threshold(
    scores: list[float],
    labels: list[bool],
    site_ids: list[str],
    *,
    case_hours: float = 3.0,
    false_alerts_per_site_day: float = 1.0,
    exposure_intervals: Iterable[tuple[str, Any, Any]] | None = None,
) -> float:
    """Choose validation F1 threshold under an explicit site-day false-alert budget."""
    if not scores or not (len(scores) == len(labels) == len(site_ids)):
        return 0.7
    candidates = sorted(set([0.0, 1.0, *(float(np.clip(x, 0.0, 1.0)) for x in scores)]))
    site_days = (
        normal_site_days(exposure_intervals)
        if exposure_intervals is not None
        else sum(site_ids.count(site) * case_hours / 24 for site in set(site_ids))
    )
    false_positive_limit = int(site_days * false_alerts_per_site_day)
    best_f1, best_threshold = -1.0, 0.7
    for threshold in candidates:
        predictions = [score > threshold for score in scores]
        tp = sum(pred and actual for pred, actual in zip(predictions, labels, strict=True))
        fp = sum(pred and not actual for pred, actual in zip(predictions, labels, strict=True))
        fn = sum(not pred and actual for pred, actual in zip(predictions, labels, strict=True))
        if fp > false_positive_limit:
            continue
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        if f1 > best_f1:
            best_f1, best_threshold = f1, threshold
    return float(best_threshold)
