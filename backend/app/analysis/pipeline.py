"""解析パイプライン（beatgrid→features→phrases→structure→scoring）。

基本設計書 §9.1 の段階を統合する。実音源解析と合成信号評価の共通経路。
"""

from __future__ import annotations

import numpy as np

from ..domain.enums import BeatSource, CueType
from ..domain.models import AnalysisResult, BeatGrid, PhraseSection
from .cue_targets import lyric_start, target_candidates
from .beatgrid import BeatGridArrays, beat_stability, estimate_beatgrid, uniform_beatgrid
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
    beats_per_phrase: int | None = None,
    beatgrid: BeatGrid | None = None,
    phrase_boundaries: tuple[int, ...] = (),
    phrase_sections: tuple[PhraseSection, ...] = (),
    cue_targets: list[str] | None = None,
    vocal_start: float | None = None,
    fingerprint: str = "n/a",
    top_k: int = 3,
) -> AnalysisResult:
    """波形から候補を生成する。拍数指定は小節数より優先する。"""
    if beats_per_bar <= 0 or bars_per_phrase <= 0:
        raise ValueError("小節・フレーズの拍数は正の値を指定してください")
    if beats_per_phrase is not None:
        if beats_per_phrase <= 0 or beats_per_phrase % beats_per_bar:
            raise ValueError("解析単位の拍数は 1 小節の拍数の倍数にしてください")
        bars_per_phrase = beats_per_phrase // beats_per_bar
    y = np.asarray(y, dtype=float)
    duration = len(y) / sr if sr else 0.0
    warnings: list[str] = []

    if beatgrid is not None:
        times = np.asarray(beatgrid.beat_times, dtype=float)
        downbeats = np.asarray(beatgrid.downbeat_indices, dtype=int)
        if len(times) < 2 or not np.all(np.isfinite(times)) or np.any(times < 0) or np.any(np.diff(times) <= 0):
            raise ValueError("rekordbox のビートグリッドが不正です")
        if np.any(downbeats < 0) or np.any(downbeats >= len(times)) or np.any(np.diff(downbeats) <= 0):
            raise ValueError("rekordbox の小節頭が不正です")
        times = times[times < duration]
        downbeats = downbeats[downbeats < len(times)]
        if len(times) < 2 or not len(downbeats):
            raise ValueError("音源の長さと rekordbox のビートグリッドが一致しません")
        grid = BeatGridArrays(beatgrid.bpm, times, downbeats, BeatSource.ANLZ)
    elif bpm is not None:
        grid = uniform_beatgrid(bpm, duration, beats_per_bar=beats_per_bar, source=BeatSource.MANUAL)
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

    anchors = sorted({int(np.argmin(np.abs(downbeats - b))) for b in phrase_boundaries if 0 <= b < len(grid.beat_times)}) if len(downbeats) else []
    if anchors:
        # 各フレーズ先頭から指定した小節数で区切り、実際の小節頭へ整列する。
        boundary_bars = list(range(anchors[0] % bars_per_phrase, anchors[0], bars_per_phrase))
        for index, start in enumerate(anchors):
            end = anchors[index + 1] if index + 1 < len(anchors) else len(downbeats)
            boundary_bars.extend(range(start, end, bars_per_phrase))
        pgrid = PhraseGrid(bars_per_phrase, 0, downbeats[sorted(set(boundary_bars))])

    candidates = generate_candidates(
        feat,
        downbeats,
        pgrid,
        beat_stability=stability,
        top_k=top_k,
    )
    if cue_targets is not None:
        candidates, target_warnings = target_candidates(feat, grid.to_domain(), candidates, cue_targets,
                                                        phrase_sections, top_k=top_k, vocal_start=vocal_start)
        warnings.extend(target_warnings)
    candidates.sort(key=lambda c: (c.cue_type.value, c.rank))

    return AnalysisResult(
        fingerprint=fingerprint,
        duration_sec=duration,
        beatgrid=grid.to_domain(),
        candidates=tuple(candidates),
        warnings=tuple(warnings),
    )


def analyze_file(
    path: str, *, bpm: float | None = None, bars_per_phrase: int = 16,
    beats_per_phrase: int | None = None, top_k: int = 3,
    beatgrid: BeatGrid | None = None, phrase_boundaries: tuple[int, ...] = (),
    phrase_sections: tuple[PhraseSection, ...] = (), cue_targets: list[str] | None = None,
) -> AnalysisResult:
    """音源ファイルをデコードして解析する（soundfile/librosa 必須）。"""
    from .decode import decode_mono
    from .fingerprint import audio_fingerprint
    from pathlib import Path
    import hashlib

    decoded = decode_mono(path)
    fp = audio_fingerprint(path)
    vocal_start = None
    lyric_warnings = []
    if cue_targets and "VOCAL_START" in cue_targets:
        lyrics = Path(path).with_suffix(".lrc")
        payload = b"none"
        try:
            if lyrics.is_file():
                if lyrics.stat().st_size > 1024 * 1024:
                    lyric_warnings.append("LRCが大きすぎるため歌い始めの読み込みを省略しました。")
                else:
                    payload = lyrics.read_bytes()
                    vocal_start = lyric_start(payload.decode("utf-8-sig", errors="replace"), decoded.duration_sec)
        except OSError:
            lyric_warnings.append("同名LRCを読み込めませんでした。")
        fp = "sha256:" + hashlib.sha256(fp.encode() + hashlib.sha256(payload).digest()).hexdigest()
    result = analyze_waveform(
        decoded.y,
        decoded.sr,
        bpm=bpm,
        bars_per_phrase=bars_per_phrase,
        beats_per_phrase=beats_per_phrase,
        beatgrid=beatgrid,
        phrase_boundaries=phrase_boundaries,
        phrase_sections=phrase_sections,
        cue_targets=cue_targets,
        vocal_start=vocal_start,
        top_k=top_k,
        fingerprint=fp,
    )
    if lyric_warnings:
        from dataclasses import replace
        result = replace(result, warnings=result.warnings + tuple(lyric_warnings))
    if decoded.is_silent:
        result = AnalysisResult(
            fingerprint=result.fingerprint,
            duration_sec=result.duration_sec,
            beatgrid=result.beatgrid,
            candidates=result.candidates,
            warnings=result.warnings + ("無音の可能性があります",),
        )
    return result
