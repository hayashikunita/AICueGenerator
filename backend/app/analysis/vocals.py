"""Vocal onset suggestions from a separated vocal stem, never from mix RMS."""
from __future__ import annotations

import numpy as np


def vocal_start_from_stems(data: dict) -> float | None:
    vocals = np.asarray(data["stems"]["vocals"], dtype=float)
    mix = np.asarray(data["mix"], dtype=float)
    hop = float(data["hop_sec"])
    if (vocals.ndim != 1 or mix.ndim != 1 or len(vocals) < 3 or len(vocals) != len(mix)
            or not np.isfinite(hop) or not .01 <= hop <= .5
            or not np.all(np.isfinite(vocals)) or not np.all(np.isfinite(mix))
            or np.any(vocals < 0) or np.any(mix < 0)):
        return None
    ratio = vocals / np.maximum(mix, 1e-8)
    plausible = (vocals >= 1e-4) & (mix > 1e-4) & (ratio >= .12)
    if not np.any(plausible):
        return None
    # Estimate relative levels only from plausible voice frames. Long silent intros
    # must not drive the reference to zero. Adapt dominance to the song so weak
    # instrumental leakage preceding a much stronger voice is not the onset.
    reference = float(np.percentile(vocals[plausible], 90))
    dominance = max(.12, min(.32, float(np.percentile(ratio[plausible], 90)) * .45))
    active = (vocals >= max(1e-4, reference * .05)) & (mix > 1e-4) & (ratio >= dominance)
    indices = np.flatnonzero(active)
    # Allow short gaps between syllables, but keep isolated shouts and attacks
    # separate from the following phrase. Require at least 1s of voice spread
    # across 1.2s, with sufficient occupancy in the first three seconds.
    gap = max(1, int(np.floor(.35 / hop)))
    groups = np.split(indices, np.flatnonzero(np.diff(indices) - 1 > gap) + 1)
    for group in groups:
        if not len(group):
            continue
        beginning = int(group[0])
        opening = group[group < beginning + int(np.ceil(3 / hop))]
        span = (int(opening[-1]) - beginning + 1) * hop
        if len(opening) * hop < 1 or span < 1.2 or len(opening) * hop / span < .45:
            continue
        # Recover a quiet consonant or breath immediately before the strong
        # onset without jumping back to an earlier tag or leakage.
        preceding = vocals[max(0, beginning - int(np.ceil(1.5 / hop))):beginning]
        background = float(np.median(preceding)) if len(preceding) else 0
        weak = (vocals >= max(1e-4, reference * .025, background * 1.8)) & (mix > 1e-4) & (ratio >= max(.08, dominance * .6))
        lower = max(0, beginning - int(np.floor(.35 / hop)))
        while beginning > lower and weak[beginning - 1]:
            beginning -= 1
        return beginning * hop
    return None


def vocal_end_from_stems(data: dict) -> float | None:
    """Last sustained voice's exclusive end, only with complete song coverage.

    Reverse the envelope so the onset detector's duration, occupancy and quiet
    edge recovery also reject isolated sounds after the last vocal phrase.
    An LRC's last line timestamp is a start and cannot supply this boundary.
    """
    import math

    duration, hop = data.get("duration_sec"), data.get("hop_sec")
    if (not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0
            or not isinstance(hop, (int, float)) or not math.isfinite(hop) or not .01 <= hop <= .5):
        return None
    if data.get("schema") == 2:
        if data.get("scan_complete") is not True or data.get("analyzed_sec") != duration:
            return None
    elif data.get("schema") != 1:
        return None
    vocals, mix = data.get("stems", {}).get("vocals"), data.get("mix")
    if vocals is None or mix is None or len(vocals) != math.ceil(duration / hop) or len(mix) != len(vocals):
        return None
    onset = vocal_start_from_stems({"stems": {"vocals": vocals[::-1]}, "mix": mix[::-1], "hop_sec": hop})
    return min(duration, len(vocals) * hop - onset) if onset is not None else None
