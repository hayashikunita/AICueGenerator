"""Bar-aligned change and non-local repetition evidence for cue suggestions."""
from __future__ import annotations

import numpy as np

from .features import BeatFeatures


def bar_descriptors(feat: BeatFeatures, downbeats: np.ndarray) -> np.ndarray:
    columns = []
    for values in (feat.chroma, feat.bands):
        if values is not None and len(values) == len(feat.rms):
            columns.append(np.sqrt(np.maximum(values, 0)))
    # Older cached/test features can still supply rhythmic/energy evidence.
    rms_scale = max(float(np.percentile(feat.rms, 95)), 1e-8) if len(feat.rms) else 1
    columns.append(np.column_stack((np.clip(feat.rms / rms_scale, 0, 2), feat.low_ratio)))
    if feat.vocal_ratio is not None:
        columns.append(np.clip(feat.vocal_ratio[:, None], 0, 1))
    beats = np.concatenate(columns, axis=1)
    return np.array([beats[start:downbeats[i + 1] if i + 1 < len(downbeats) else len(beats)].mean(axis=0)
                     for i, start in enumerate(downbeats)]) if len(downbeats) else np.empty((0, beats.shape[1]))


def boundary_strengths(feat: BeatFeatures, downbeats: np.ndarray) -> np.ndarray:
    descriptors = bar_descriptors(feat, downbeats)
    strength = np.zeros(len(feat.rms))
    for bar in range(1, len(descriptors)):
        before = descriptors[max(0, bar - 2):bar].mean(axis=0)
        after = descriptors[bar:bar + 2].mean(axis=0)
        strength[downbeats[bar]] = float(np.linalg.norm(after - before))
    return strength


def repeated_section_scores(feat: BeatFeatures, downbeats: np.ndarray, *, window_bars: int = 4) -> np.ndarray:
    descriptors = bar_descriptors(feat, downbeats)
    n = len(descriptors)
    scores = np.zeros(n)
    width = min(window_bars, n // 3)
    if width < 2:
        return scores
    # Concatenating several bars compares ordered passages, not isolated beats.
    windows = np.array([descriptors[i:i + width].ravel() for i in range(n - width + 1)])
    unit = windows / np.maximum(np.linalg.norm(windows, axis=1, keepdims=True), 1e-8)
    # Bound memory on long mixes: compare one query at a time (no N x N array).
    for bar in range(len(windows)):
        remote = np.abs(np.arange(len(windows)) - bar) >= width * 2
        if not np.any(remote) or np.linalg.norm(windows[bar]) < 1e-8:
            continue
        similarity = unit[remote] @ unit[bar]
        best = float(np.max(similarity))
        background = float(np.percentile(similarity, 50))
        # An unchanging loop everywhere is not distinctive repetition evidence.
        scores[bar] = np.clip((best - background) / .08, 0, 1) * np.clip((best - .80) / .18, 0, 1)
    return scores
