"""解析パイプライン（beatgrid→features→phrases→structure→scoring）。

基本設計書 §9.1 の段階を統合する。実音源解析と合成信号評価の共通経路。
"""

from __future__ import annotations

import numpy as np

from ..domain.enums import BeatSource, CueType
from ..domain.models import AnalysisResult, BeatGrid, PhraseSection
from ..domain.cue_targets import INTRO_OUTRO_DEFAULT_TARGETS
from .cue_targets import lyric_start, target_candidates
from .beatgrid import BeatGridArrays, beat_stability, estimate_beatgrid, uniform_beatgrid
from .features import extract_features
from .phrases import PhraseGrid, best_phase_grid, phrase_grids
from .structure import generate_candidates
from .structure_evidence import boundary_strengths, repeated_section_scores
from .vocals import vocal_start_from_stems, vocal_end_from_stems
from .intro_outro import intro_outro_candidates
from .fingerprint import AudioInput, file_analysis_inputs

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
    end_alignment_bars: int = 1,
    vocal_start: float | None = None,
    vocal_start_source: str = "LRC",
    vocal_end: float | None = None,
    stem_analysis: dict | None = None,
    intro_outro: dict | None = None,
    legacy_vocal_start: bool = False,
    legacy_vocal_end: bool = False,
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
    if intro_outro is not None:
        bars_per_phrase = 1  # Scan saved bars; the other tabs' phrase setting is unrelated.
    y = np.asarray(y, dtype=float)
    duration = len(y) / sr if sr else 0.0
    warnings: list[str] = []
    if vocal_end is not None and (not np.isfinite(vocal_end) or not 0 < vocal_end <= duration):
        vocal_end = None

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
    if stem_analysis is not None and stem_analysis.get("scope") != "VOCAL":
        frame_times = np.arange(len(stem_analysis["mix"])) * stem_analysis["hop_sec"]
        vocal = np.asarray(stem_analysis["stems"]["vocals"])
        mix = np.asarray(stem_analysis["mix"])
        feat.vocal_ratio = np.interp(grid.beat_times, frame_times, np.clip(vocal / np.maximum(mix, 1e-8), 0, 1))
    stability = beat_stability(grid.beat_times)

    downbeats = grid.downbeat_indices
    pgrid = best_phase_grid(downbeats, boundary_strengths(feat, downbeats), bars_per_phrase=bars_per_phrase)
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
        cue_types=(CueType.INTRO_END, CueType.OUTRO) if intro_outro is not None else None,
    )
    if intro_outro is not None:
        candidates, target_warnings = intro_outro_candidates(feat, grid.to_domain(), candidates, phrase_sections, intro_outro, duration,
            vocal_start=vocal_start, vocal_start_source=vocal_start_source, vocal_end=vocal_end)
        warnings.extend(target_warnings)
    elif cue_targets is not None:
        candidates, target_warnings = target_candidates(feat, grid.to_domain(), candidates, cue_targets,
                                                        phrase_sections, top_k=top_k, vocal_start=vocal_start,
                                                        vocal_start_source=vocal_start_source, vocal_end=vocal_end, end_alignment_bars=end_alignment_bars,
                                                        repetition_scores=repeated_section_scores(feat, downbeats))
        warnings.extend(target_warnings)
    elif legacy_vocal_start or legacy_vocal_end:
        voice_targets = [target for target, enabled in (("VOCAL_START", legacy_vocal_start), ("VOCAL_END", legacy_vocal_end)) if enabled]
        vocal_candidates, target_warnings = target_candidates(feat, grid.to_domain(), [], voice_targets, (),
            top_k=1, vocal_start=vocal_start, vocal_start_source=vocal_start_source, vocal_end=vocal_end, allow_vocal_fallback=False)
        candidates.extend(vocal_candidates)
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
    end_alignment_bars: int = 1,
    stem_analysis: dict | None = None,
    intro_outro: dict | None = None,
    legacy_vocal_start: bool = False,
    legacy_vocal_end: bool = False,
    audio_input: AudioInput | None = None,
) -> AnalysisResult:
    """音源ファイルをデコードして解析する（soundfile/librosa 必須）。"""
    from .decode import decode_mono

    audio_input = audio_input or AudioInput.read(path)
    audio_input.verify(path)
    decoded = decode_mono(path)
    legacy_vocal_start = legacy_vocal_start and intro_outro is None and cue_targets is None
    legacy_vocal_end = legacy_vocal_end and intro_outro is None and cue_targets is None
    if intro_outro is not None:
        cue_targets = [target for target in intro_outro.get("targets", INTRO_OUTRO_DEFAULT_TARGETS) if target in {"VOCAL_START", "VOCAL_END"}] or None
        if not cue_targets:
            stem_analysis = None
    vocal_requested = legacy_vocal_start or bool(cue_targets and "VOCAL_START" in cue_targets)
    end_requested = legacy_vocal_end or bool(cue_targets and "VOCAL_END" in cue_targets)
    vocal_end = vocal_end_from_stems(stem_analysis) if end_requested and stem_analysis is not None else None
    fp, payload, lyric_warnings = file_analysis_inputs(
        path, vocal_requested=vocal_requested, stem_analysis=stem_analysis, audio_input=audio_input,
    )
    vocal_start = lyric_start(payload.decode("utf-8-sig", errors="replace"), decoded.duration_sec) if payload is not None else None
    vocal_source = "LRC"
    if vocal_start is None and stem_analysis is not None and vocal_requested:
        vocal_start = vocal_start_from_stems(stem_analysis)
        vocal_source = "DEMUCS"
        if stem_analysis.get("scope") == "VOCAL":
            vocal_source = "DEMUCS_VOCAL"
        if vocal_start is None:
            lyric_warnings.append("分離したボーカルから継続する開始位置を特定できませんでした。" + ("歌い始めの候補は省略します。" if intro_outro is not None or legacy_vocal_start else "Verse先頭がある場合は仮候補として表示します。"))
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
        end_alignment_bars=end_alignment_bars,
        vocal_start=vocal_start,
        vocal_start_source=vocal_source,
        vocal_end=vocal_end,
        stem_analysis=stem_analysis,
        intro_outro=intro_outro,
        legacy_vocal_start=legacy_vocal_start,
        legacy_vocal_end=legacy_vocal_end,
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
    audio_input.verify(path)
    return result
