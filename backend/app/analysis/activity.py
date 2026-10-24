"""Find sustained audible activity on the saved beat grid.

This rejects isolated ticks; it does not classify instruments or vocals. A
robust reference keeps a loud transient from hiding a quiet intro or fade.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ActivityBounds:
    start_beat: int
    end_beat: int  # Exclusive; may equal the number of saved beats.


def activity_bounds(rms: np.ndarray) -> ActivityBounds | None:
    levels = np.asarray(rms, dtype=float)
    if levels.ndim != 1 or not len(levels):
        return None
    levels = np.where(np.isfinite(levels), np.maximum(levels, 0), 0)
    reference = float(np.percentile(levels, 90))
    # The floor also excludes the sqrt(epsilon) noise in RMS extraction.
    threshold = max(1e-4, reference * 10 ** (-50 / 20))
    active = np.flatnonzero(levels > threshold)
    if len(active) < 2:
        return None
    # At least two active beats within three beats are required. Repeated
    # percussion with a silent beat in between remains valid musical activity.
    near = np.diff(active) <= 2
    supported = np.zeros(len(active), dtype=bool)
    supported[:-1] |= near
    supported[1:] |= near
    sustained = active[supported]
    if not len(sustained):
        return None
    return ActivityBounds(int(sustained[0]), int(sustained[-1]) + 1)
