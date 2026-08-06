"""構造解析による候補生成（基本設計書 §9.2 structure, §7 House/EDM）。

小節集約したエネルギー曲線とフレーズ境界から、種類別(Intro/Break/Build/Drop/Outro)の
候補をフレーズ境界にスナップして生成し、scoring で信頼度を付与して Top-3 を返す。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.enums import CueType
from ..domain.models import CueCandidate
from .features import BeatFeatures
from .phrases import PhraseGrid
from .scoring import score_candidate

_EPS = 1e-9


@dataclass
class BarProfile:
    """小節単位に集約した特徴量。"""

    start_beats: np.ndarray  # 各小節先頭の拍添字
    energy: np.ndarray  # 正規化 RMS
    low: np.ndarray  # 低域比率
    onset: np.ndarray  # オンセット強度（正規化）
    flux: np.ndarray  # フラックス（正規化）


def aggregate_bars(feat: BeatFeatures, downbeats: np.ndarray) -> BarProfile:
    """拍単位特徴を小節単位へ集約する。"""
    downbeats = np.asarray(downbeats, dtype=int)
    norm = feat.normalized()
    n_beats = len(feat.beat_times)
    starts = []
    energy = []
    low = []
    onset = []
    flux = []
    for i, db in enumerate(downbeats):
        end = int(downbeats[i + 1]) if i + 1 < len(downbeats) else n_beats
        sl = slice(int(db), max(int(db) + 1, end))
        starts.append(int(db))
        energy.append(float(np.mean(norm.rms[sl])))
        low.append(float(np.mean(feat.low_ratio[sl])))
        onset.append(float(np.mean(norm.onset[sl])))
        flux.append(float(np.mean(norm.flux[sl])))
    return BarProfile(
        start_beats=np.asarray(starts, dtype=int),
        energy=np.asarray(energy, dtype=float),
        low=np.asarray(low, dtype=float),
        onset=np.asarray(onset, dtype=float),
        flux=np.asarray(flux, dtype=float),
    )


def _window_delta(x: np.ndarray, bar: int, w: int) -> float:
    before = x[max(0, bar - w) : bar]
    after = x[bar : bar + w]
    b = float(np.mean(before)) if before.size else 0.0
    a = float(np.mean(after)) if after.size else 0.0
    return a - b


def _rise_slope(x: np.ndarray, bar: int, w: int) -> float:
    seg = x[max(0, bar - w) : bar]
    if seg.size < 2:
        return 0.0
    t = np.arange(seg.size)
    slope = float(np.polyfit(t, seg, 1)[0])
    return slope


def _phrase_boundary_bars(grid: PhraseGrid, profile: BarProfile) -> list[int]:
    """フレーズ境界の拍添字を小節添字へ写像する。"""
    bars: list[int] = []
    for beat in grid.boundary_beats:
        j = int(np.argmin(np.abs(profile.start_beats - int(beat))))
        bars.append(j)
    return sorted(set(bars))


def _mk_candidate(
    cue_type: CueType,
    bar: int,
    profile: BarProfile,
    beat_times: np.ndarray,
    components: dict[str, float],
    pssi_bonus: float,
    rank: int,
) -> CueCandidate:
    beat_index = int(profile.start_beats[bar])
    time_sec = float(beat_times[beat_index]) if beat_index < len(beat_times) else 0.0
    confidence, evidence = score_candidate(components, pssi_bonus=pssi_bonus)
    return CueCandidate(
        cue_type=cue_type,
        time_sec=time_sec,
        beat_index=beat_index,
        confidence=confidence,
        rank=rank,
        evidence=evidence,
        phrase_aligned=True,
    )


def generate_candidates(
    feat: BeatFeatures,
    downbeats: np.ndarray,
    grid: PhraseGrid,
    *,
    beat_stability: float = 1.0,
    window_bars: int = 4,
    top_k: int = 3,
    pssi_types: dict[CueType, set[int]] | None = None,
    pssi_at_bar: dict[int, int] | None = None,
) -> list[CueCandidate]:
    """種類別 Top-k 候補を生成する。

    pssi_at_bar: 小節添字 -> PSSI フレーズ型。pssi_types: Cue種別 -> 整合するPSSI型集合。
    整合時はフレーズ整合成分へ加点する。
    """
    profile = aggregate_bars(feat, downbeats)
    n = len(profile.energy)
    if n < 2:
        return []
    boundaries = _phrase_boundary_bars(grid, profile)
    beat_times = np.asarray(feat.beat_times, dtype=float)
    w = max(1, window_bars)

    # 境界ごとの変化量を集計して正規化スケールを得る。
    d_energy = {b: _window_delta(profile.energy, b, w) for b in boundaries}
    d_low = {b: _window_delta(profile.low, b, w) for b in boundaries}
    d_onset = {b: _window_delta(profile.onset, b, w) for b in boundaries}
    rise = {b: _rise_slope(profile.onset, b, w) for b in boundaries}
    max_abs_e = max((abs(v) for v in d_energy.values()), default=1.0) or 1.0
    max_abs_o = max((abs(v) for v in d_onset.values()), default=1.0) or 1.0
    max_rise = max((abs(v) for v in rise.values()), default=1.0) or 1.0

    def pssi_bonus(cue: CueType, bar: int) -> float:
        if not (pssi_types and pssi_at_bar and bar in pssi_at_bar):
            return 0.0
        return 0.2 if pssi_at_bar[bar] in pssi_types.get(cue, set()) else 0.0

    out: list[CueCandidate] = []
    third = n / 3.0

    for cue in CueType:
        scored: list[tuple[float, int, dict[str, float]]] = []
        for b in boundaries:
            de, dl, do = d_energy[b], d_low[b], d_onset[b]
            energy_up = max(de, 0.0) / max_abs_e
            energy_dn = max(-de, 0.0) / max_abs_e
            onset_up = max(do, 0.0) / max_abs_o
            rise_up = max(rise[b], 0.0) / max_rise

            if cue is CueType.DROP:
                if not (de > 0 and dl > 0 and b >= third * 0.5):
                    continue
                comp = {"energy_diff": energy_up, "percussive_onset": onset_up}
                strength = energy_up + onset_up
            elif cue is CueType.INTRO_END:
                if not (de > 0 and b <= third):
                    continue
                comp = {"energy_diff": energy_up, "percussive_onset": onset_up}
                strength = energy_up
            elif cue is CueType.BREAK:
                if not (de < 0 and dl < 0 and third * 0.5 <= b <= third * 2.5):
                    continue
                comp = {"energy_diff": energy_dn, "percussive_onset": onset_up * 0.5}
                strength = energy_dn
            elif cue is CueType.BUILD:
                if not (rise[b] > 0 and b >= third * 0.5):
                    continue
                comp = {"energy_diff": rise_up, "percussive_onset": onset_up}
                strength = rise_up + onset_up
            elif cue is CueType.OUTRO:
                if not (de < 0 and b >= third * 2.0):
                    continue
                comp = {"energy_diff": energy_dn, "percussive_onset": 0.0}
                strength = energy_dn
            else:  # pragma: no cover - 種別網羅
                continue

            components = {
                "beat_stability": beat_stability,
                "phrase_alignment": 1.0,
                "energy_diff": comp.get("energy_diff", 0.0),
                "percussive_onset": comp.get("percussive_onset", 0.0),
                "repetition": _repetition(profile.energy, b, w),
            }
            scored.append((strength, b, components))

        scored.sort(key=lambda t: t[0], reverse=True)
        for rank, (_, b, components) in enumerate(scored[:top_k], start=1):
            out.append(
                _mk_candidate(
                    cue, b, profile, beat_times, components, pssi_bonus(cue, b), rank
                )
            )
    return out


def _repetition(energy: np.ndarray, bar: int, w: int) -> float:
    """境界近傍の局所的一貫性を 0..1 で近似（分散が小さいほど高い）。"""
    seg = energy[max(0, bar - w) : bar + w]
    if seg.size < 2:
        return 0.0
    var = float(np.var(seg))
    return float(np.clip(1.0 - var * 4.0, 0.0, 1.0))
