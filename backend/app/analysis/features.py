"""特徴量抽出（基本設計書 §9.2 features）。

numpy のみで実装。拍全体から RMS / 低域比率 / スペクトルフラックス /
オンセット強度・12音のクロマ・16帯域の音色を求める。
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
    chroma: np.ndarray | None = None  # (N, 12), harmonic content
    bands: np.ndarray | None = None  # (N, 16), gain-independent timbre
    vocal_ratio: np.ndarray | None = None

    def normalized(self) -> "BeatFeatures":
        """各特徴量を 0..1 に正規化した複製を返す。"""
        return BeatFeatures(
            beat_times=self.beat_times,
            rms=_minmax(self.rms),
            low_ratio=np.clip(self.low_ratio, 0.0, 1.0),
            flux=_minmax(self.flux),
            onset=_minmax(self.onset),
            chroma=self.chroma,
            bands=self.bands,
            vocal_ratio=self.vocal_ratio,
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


def _musical_spectrum(seg: np.ndarray, sr: int) -> tuple[float, np.ndarray, np.ndarray]:
    """Describe the entire beat, rather than only its first 512 samples."""
    if seg.size < 2:
        return 0.0, np.zeros(12), np.zeros(16)
    spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) / len(seg)
    frequencies = np.fft.rfftfreq(len(seg), 1 / sr)
    low = float(spectrum[frequencies < 200].sum() / (spectrum.sum() + _EPS))
    valid = (frequencies >= 55) & (frequencies <= min(5000, sr / 2))
    pitches = np.rint(69 + 12 * np.log2(frequencies[valid] / 440)).astype(int) % 12
    chroma = np.bincount(pitches, weights=spectrum[valid], minlength=12)
    edges = np.geomspace(40, max(41, sr / 2), 17)
    indices = np.searchsorted(edges, frequencies, side="right") - 1
    selected = (indices >= 0) & (indices < 16)
    bands = np.bincount(indices[selected], weights=spectrum[selected], minlength=16)
    return low, chroma, bands


def extract_features(y: np.ndarray, sr: int, beat_times: np.ndarray) -> BeatFeatures:
    """拍単位の特徴量を抽出する。"""
    y = np.asarray(y, dtype=float)
    beat_times = np.asarray(beat_times, dtype=float)
    n = len(beat_times)
    rms = np.zeros(n)
    low = np.zeros(n)
    spectra = []
    chroma = np.zeros((n, 12))
    bands = np.zeros((n, 16))

    segs = _beat_segments(y, sr, beat_times)
    for i, seg in enumerate(segs):
        rms[i] = float(np.sqrt(np.mean(seg**2) + _EPS)) if seg.size else 0.0
        low[i], harmonic, spectrum = _musical_spectrum(seg, sr)
        chroma[i] = harmonic / (harmonic.sum() + _EPS)
        bands[i] = spectrum / (spectrum.sum() + _EPS)
        spectra.append(spectrum)

    flux = np.zeros(n)
    for i in range(1, n):
        diff = spectra[i] - spectra[i - 1]
        flux[i] = float(np.sum(np.maximum(diff, 0.0)))

    onset = np.zeros(n)
    onset[1:] = np.maximum(np.diff(rms), 0.0)

    return BeatFeatures(beat_times=beat_times, rms=rms, low_ratio=low, flux=flux, onset=onset, chroma=chroma, bands=bands)


def repetition_matrix(bar_vectors: np.ndarray) -> np.ndarray:
    """小節特徴ベクトル間のコサイン類似度行列（反復性の根拠）。"""
    if bar_vectors.ndim != 2 or bar_vectors.shape[0] == 0:
        return np.zeros((0, 0))
    norm = np.linalg.norm(bar_vectors, axis=1, keepdims=True) + _EPS
    unit = bar_vectors / norm
    return unit @ unit.T
