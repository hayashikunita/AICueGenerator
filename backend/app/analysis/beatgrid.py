"""ビートグリッド生成（基本設計書 §9.2 beatgrid）。

優先度: ANLZ(PQTZ) > librosa 推定 > 一様グリッド。
本モジュールは numpy 配列で扱い、必要に応じて domain.BeatGrid へ変換する。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..domain.enums import BeatSource
from ..domain.models import BeatGrid


@dataclass
class BeatGridArrays:
    """解析内部用のビートグリッド（numpy 配列）。"""

    bpm: float
    beat_times: np.ndarray  # shape (N,), 秒
    downbeat_indices: np.ndarray  # beat_times への添字, shape (M,)
    source: BeatSource

    def to_domain(self) -> BeatGrid:
        return BeatGrid(
            bpm=float(self.bpm),
            beat_times=tuple(float(t) for t in self.beat_times),
            downbeat_indices=tuple(int(i) for i in self.downbeat_indices),
            source=self.source,
        )


def uniform_beatgrid(
    bpm: float,
    duration_sec: float,
    *,
    beats_per_bar: int = 4,
    phase_sec: float = 0.0,
    source: BeatSource = BeatSource.LIBROSA,
) -> BeatGridArrays:
    """一定 BPM の一様グリッドを生成する（評価・テスト・フォールバック用）。"""
    if bpm <= 0:
        raise ValueError("bpm は正の値である必要があります")
    beat_period = 60.0 / bpm
    n = int(max(0, (duration_sec - phase_sec)) / beat_period) + 1
    beat_times = phase_sec + np.arange(n, dtype=float) * beat_period
    beat_times = beat_times[beat_times <= duration_sec + 1e-9]
    downbeats = np.arange(0, len(beat_times), beats_per_bar, dtype=int)
    return BeatGridArrays(bpm, beat_times, downbeats, source)


def estimate_beatgrid(y: np.ndarray, sr: int, *, beats_per_bar: int = 4) -> BeatGridArrays:
    """librosa による拍推定（遅延 import）。ダウンビートは近似で beats_per_bar 毎。"""
    try:
        import librosa
    except ImportError as exc:  # pragma: no cover - 依存未導入時
        raise RuntimeError("librosa 未導入のため拍推定できません") from exc

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    downbeats = np.arange(0, len(beat_times), beats_per_bar, dtype=int)
    return BeatGridArrays(bpm, np.asarray(beat_times, dtype=float), downbeats, BeatSource.LIBROSA)


def beat_stability(beat_times: np.ndarray) -> float:
    """拍間隔の安定度を 0..1 で返す（等間隔なら 1 に近い）。"""
    if len(beat_times) < 3:
        return 0.0
    intervals = np.diff(beat_times)
    mean = float(np.mean(intervals))
    if mean <= 0:
        return 0.0
    cv = float(np.std(intervals) / mean)  # 変動係数
    return float(np.clip(1.0 - cv, 0.0, 1.0))
