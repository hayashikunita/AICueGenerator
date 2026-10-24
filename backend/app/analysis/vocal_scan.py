"""Progressive vocal-only scan; a quiet or ambiguous prefix never ends the scan."""
from __future__ import annotations

import math
import numpy as np

try:
    from .vocals import vocal_start_from_stems
except ImportError:  # Standalone inference interpreter.
    from vocals import vocal_start_from_stems


def confirmed_early_voice(data: dict) -> bool:
    onset = vocal_start_from_stems(data)
    if onset is None or onset + 3 > data["analyzed_sec"]:
        return False
    hop = data["hop_sec"]
    start = round(onset / hop)
    stop = start + math.ceil(3 / hop)
    vocals = np.asarray(data["stems"]["vocals"][start:stop])
    mix = np.asarray(data["mix"][start:stop])
    # Early exit needs stronger evidence than the final full-coverage detector.
    # Weak instrumental leakage or a short tag must not stop later inspection.
    strong = (vocals >= 1e-4) & (mix > 1e-4) & (vocals / np.maximum(mix, 1e-8) >= .3)
    return np.count_nonzero(strong) * hop >= 1.5


def scan_vocals(duration: float, separate, *, on_window=None, window_sec: int = 30, require_end: bool = False) -> dict:
    if not math.isfinite(duration) or duration <= 0 or window_sec <= 0:
        raise ValueError("Invalid vocal scan duration")
    result = {"schema": 2, "model": "htdemucs", "scope": "VOCAL", "hop_sec": .1,
              "duration_sec": duration, "analyzed_sec": 0, "scan_complete": False,
              "mix": [], "stems": {"vocals": []}}
    for start in range(0, math.ceil(duration), window_sec):
        end = min(start + window_sec, duration)
        if on_window:
            on_window({"scope": "VOCAL", "scan_start_sec": start, "scan_end_sec": end, "audio_duration_sec": duration})
        mix, vocals = separate(start, end)
        expected = math.ceil(end / .1) - len(result["mix"])
        if len(mix) != expected or len(vocals) != expected:
            raise ValueError("Vocal scan envelope does not match audio coverage")
        result["mix"].extend(mix)
        result["stems"]["vocals"].extend(vocals)
        result.update(analyzed_sec=end, scan_complete=end == duration)
        if result["scan_complete"] or (not require_end and confirmed_early_voice(result)):
            break
    return result
