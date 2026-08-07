"""解析パイプライン（beatgrid→features→phrases→structure→scoring）。

基本設計書 §9.1 の段階を統合する。実音源解析と合成信号評価の共通経路。
"""

from __future__ import annotations

import numpy as np

from ..domain.enums import BeatSource, CueType
from ..domain.models import AnalysisResult
from .beatgrid import beat_stability, estimate_beatgrid, uniform_beatgrid
from .features import extract_features
from .phrases import PhraseGrid, best_phase_grid, phrase_grids
from .structure import generate_candidates

# PSSI フレーズ型 → Cue 種別の対応（整合時に加点）。型番号は仮置きで P0 S8 後に確定。
DEFAULT_PSSI_MAP: dict[CueType, set[int]] = {
    CueType.INTRO_END: {1},
    CueType.BREAK: {2, 3},
    CueType.BUILD: {4},
    CueType.DROP: {5},
    CueType.OUTRO: {6},
}


def analyze_waveform(
    y: np.ndarray,
    sr: int,
    *,
    bpm: float | None = None,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 16,
    fingerprint: str = "n/a",
    top_k: int = 3,
) -> AnalysisResult:
    """波形から候補を生成する。bpm 指定時は一様グリッド、無指定なら librosa 推定。"""
    y = np.asarray(y, dtype=float)
    duration = len(y) / sr if sr else 0.0
    warnings: list[str] = []

    if bpm is not None:
        grid = uniform_beatgrid(bpm, duration, beats_per_bar=beats_per_bar, source=BeatSource.ANLZ)
    else:
        try:
            grid = estimate_beatgrid(y, sr, beats_per_bar=beats_per_bar)
        except RuntimeError as exc:
            warnings.append(str(exc))
            grid = uniform_beatgrid(128.0, duration, beats_per_bar=beats_per_bar)

    feat = extract_features(y, sr, grid.beat_times)
    stability = beat_stability(grid.beat_times)

    downbeats = grid.downbeat_indices
    pgrid = best_phase_grid(downbeats, feat.onset, bars_per_phrase=bars_per_phrase)
    if pgrid is None:
        grids = phrase_grids(downbeats, bars_options=(bars_per_phrase,))
        pgrid = grids[0] if grids else PhraseGrid(bars_per_phrase, 0, np.asarray([], dtype=int))
        if not grids:
            warnings.append("フレーズグリッドを構成できませんでした（曲が短すぎる可能性）")

    candidates = generate_candidates(
        feat,
        downbeats,
        pgrid,
        beat_stability=stability,
        top_k=top_k,
    )
    candidates.sort(key=lambda c: (c.cue_type.value, c.rank))

    return AnalysisResult(
        fingerprint=fingerprint,
        duration_sec=duration,
        beatgrid=grid.to_domain(),
        candidates=tuple(candidates),
        warnings=tuple(warnings),
    )


def analyze_file(
    path: str, *, bpm: float | None = None, bars_per_phrase: int = 16, top_k: int = 3
) -> AnalysisResult:
    """音源ファイルをデコードして解析する（soundfile/librosa 必須）。"""
    from .decode import decode_mono
    from .fingerprint import audio_fingerprint

    decoded = decode_mono(path)
    fp = audio_fingerprint(path)
    result = analyze_waveform(
        decoded.y,
        decoded.sr,
        bpm=bpm,
        bars_per_phrase=bars_per_phrase,
        top_k=top_k,
        fingerprint=fp,
    )
    if decoded.is_silent:
        result = AnalysisResult(
            fingerprint=result.fingerprint,
            duration_sec=result.duration_sec,
            beatgrid=result.beatgrid,
            candidates=result.candidates,
            warnings=result.warnings + ("無音の可能性があります",),
        )
    return result
