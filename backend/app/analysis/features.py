"""特徴量抽出（基本設計書 §9.2 features）。

numpy のみで実装。波形と拍時刻から拍単位の RMS / 低域比率 / スペクトルフラックス /
オンセット強度を求める。HPSS（打楽器成分分離）は librosa 依存のため任意拡張とし、
本実装ではフラックス/オンセットで打楽器性を近似する。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_EPS = 1e-9


@dataclass
class BeatFeatures:
    """拍単位の特徴量（各配列 shape (N,) = 拍数）。"""

    beat_times: np.ndarray
    rms: np.ndarray
    low_ratio: np.ndarray  # <200Hz のエネルギー比率
    flux: np.ndarray  # スペクトルフラックス（正の変化）
    onset: np.ndarray  # RMS の半波整流差分

    def normalized(self) -> "BeatFeatures":
        """各特徴量を 0..1 に正規化した複製を返す。"""
        return BeatFeatures(
            beat_times=self.beat_times,
            rms=_minmax(self.rms),
            low_ratio=np.clip(self.low_ratio, 0.0, 1.0),
            flux=_minmax(self.flux),
            onset=_minmax(self.onset),
        )


def _minmax(x: np.ndarray) -> np.ndarray:
    lo = float(np.min(x)) if x.size else 0.0
    hi = float(np.max(x)) if x.size else 0.0
    if hi - lo < _EPS:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def _beat_segments(y: np.ndarray, sr: int, beat_times: np.ndarray) -> list[np.ndarray]:
    idx = np.clip((beat_times * sr).astype(int), 0, len(y))
    segs: list[np.ndarray] = []
    for i in range(len(beat_times)):
        start = int(idx[i])
        end = int(min(len(y), beat_times[i + 1] * sr)) if i + 1 < len(beat_times) else len(y)
        segs.append(y[start:end] if end > start else y[start : start + 1])
    return segs


def _low_ratio(seg: np.ndarray, sr: int, cutoff_hz: float = 200.0) -> float:
    if seg.size < 2:
        return 0.0
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), d=1.0 / sr)
    total = float(np.sum(spec) + _EPS)
    low = float(np.sum(spec[freqs < cutoff_hz]))
    return low / total


def _spectrum(seg: np.ndarray, n: int = 512) -> np.ndarray:
    if seg.size == 0:
        return np.zeros(n // 2 + 1)
    w = seg[: n] if seg.size >= n else np.pad(seg, (0, n - seg.size))
    return np.abs(np.fft.rfft(w * np.hanning(len(w))))


def extract_features(y: np.ndarray, sr: int, beat_times: np.ndarray) -> BeatFeatures:
    """拍単位の特徴量を抽出する。"""
    y = np.asarray(y, dtype=float)
    beat_times = np.asarray(beat_times, dtype=float)
    n = len(beat_times)
    rms = np.zeros(n)
    low = np.zeros(n)
    spectra = []

    segs = _beat_segments(y, sr, beat_times)
    for i, seg in enumerate(segs):
        rms[i] = float(np.sqrt(np.mean(seg**2) + _EPS)) if seg.size else 0.0
        low[i] = _low_ratio(seg, sr)
        spectra.append(_spectrum(seg))

    flux = np.zeros(n)
    for i in range(1, n):
        diff = spectra[i] - spectra[i - 1]
        flux[i] = float(np.sum(np.maximum(diff, 0.0)))

    onset = np.zeros(n)
    onset[1:] = np.maximum(np.diff(rms), 0.0)

    return BeatFeatures(beat_times=beat_times, rms=rms, low_ratio=low, flux=flux, onset=onset)


def repetition_matrix(bar_vectors: np.ndarray) -> np.ndarray:
    """小節特徴ベクトル間のコサイン類似度行列（反復性の根拠）。"""
    if bar_vectors.ndim != 2 or bar_vectors.shape[0] == 0:
        return np.zeros((0, 0))
    norm = np.linalg.norm(bar_vectors, axis=1, keepdims=True) + _EPS
    unit = bar_vectors / norm
    return unit @ unit.T
