"""評価・テスト用の合成 EDM 信号生成。

House/EDM の典型構成(Intro→Build→Drop→Break→Drop→Outro)を持つモノラル波形を
決定的に生成する。実音源が無くても解析パイプラインを評価できる。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# (小節数, キック振幅, ノイズ振幅) の並び。
_DEFAULT_SECTIONS: tuple[tuple[int, float, float], ...] = (
    (16, 0.30, 0.00),  # intro
    (16, 0.50, 0.40),  # build
    (16, 1.00, 0.80),  # drop1
    (16, 0.10, 0.50),  # break
    (16, 1.00, 0.80),  # drop2
    (16, 0.40, 0.15),  # outro
)


@dataclass
class SyntheticTrack:
    y: np.ndarray
    sr: int
    bpm: float
    beats_per_bar: int
    section_boundaries_bar: tuple[int, ...]  # 各セクション開始小節


def synthesize_edm(
    *,
    bpm: float = 128.0,
    sr: int = 22050,
    beats_per_bar: int = 4,
    seed: int = 0,
    sections: tuple[tuple[int, float, float], ...] = _DEFAULT_SECTIONS,
) -> SyntheticTrack:
    """決定的に EDM 風波形を生成する。"""
    rng = np.random.default_rng(seed)
    bar_kick: list[float] = []
    bar_noise: list[float] = []
    boundaries: list[int] = []
    cursor = 0
    for nbars, k, nz in sections:
        boundaries.append(cursor)
        bar_kick.extend([k] * nbars)
        bar_noise.extend([nz] * nbars)
        cursor += nbars

    total_bars = len(bar_kick)
    beat_period = 60.0 / bpm
    spb = int(round(sr * beat_period))  # samples per beat
    y = np.zeros(total_bars * beats_per_bar * spb, dtype=float)

    # キックの1拍分エンベロープ（減衰する 60Hz サイン）。
    t_beat = np.arange(spb) / sr
    kick_wave = np.sin(2 * np.pi * 60.0 * t_beat) * np.exp(-t_beat * 18.0)

    beat = 0
    for bar in range(total_bars):
        for _ in range(beats_per_bar):
            start = beat * spb
            end = start + spb
            y[start:end] += bar_kick[bar] * kick_wave
            if bar_noise[bar] > 0:
                y[start:end] += bar_noise[bar] * rng.normal(0.0, 0.3, size=spb)
            beat += 1

    peak = float(np.max(np.abs(y))) or 1.0
    y = y / (peak * 1.05)
    return SyntheticTrack(
        y=y,
        sr=sr,
        bpm=bpm,
        beats_per_bar=beats_per_bar,
        section_boundaries_bar=tuple(boundaries),
    )
