"""フレーズグリッド（基本設計書 §9.2 phrases）。

ダウンビート列から 8/16/32 小節のフレーズ境界を生成する。位相（開始オフセット）を
複数試し、Cue はフレーズ境界へスナップさせる（要件: フレーズ整合）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PhraseGrid:
    """1つのフレーズ仮説。boundary_beats は beat_times への添字列。"""

    bars_per_phrase: int
    phase_bars: int
    boundary_beats: np.ndarray  # 各フレーズ先頭の拍添字

    def nearest_boundary(self, beat_index: int) -> int:
        """指定拍に最も近いフレーズ境界の拍添字を返す。"""
        if self.boundary_beats.size == 0:
            return beat_index
        j = int(np.argmin(np.abs(self.boundary_beats - beat_index)))
        return int(self.boundary_beats[j])

    def distance_bars(self, beat_index: int, downbeats: np.ndarray) -> float:
        """指定拍とフレーズ境界の距離を小節数で返す（整合度評価用）。"""
        nearest = self.nearest_boundary(beat_index)
        db = np.asarray(downbeats)
        if db.size == 0:
            return 0.0
        bi = int(np.searchsorted(db, beat_index))
        bn = int(np.searchsorted(db, nearest))
        return abs(bi - bn)


def phrase_grids(
    downbeats: np.ndarray,
    *,
    bars_options: tuple[int, ...] = (8, 16, 32),
) -> list[PhraseGrid]:
    """ダウンビート列から複数の位相・小節長のフレーズ仮説を列挙する。"""
    downbeats = np.asarray(downbeats, dtype=int)
    grids: list[PhraseGrid] = []
    n_bars = len(downbeats)
    for bars in bars_options:
        if n_bars < bars:
            continue
        for phase in range(bars):
            boundary_bar_idx = np.arange(phase, n_bars, bars, dtype=int)
            boundary_beats = downbeats[boundary_bar_idx]
            grids.append(PhraseGrid(bars, phase, boundary_beats))
    return grids


def best_phase_grid(
    downbeats: np.ndarray,
    strength: np.ndarray,
    *,
    bars_per_phrase: int = 16,
) -> PhraseGrid | None:
    """境界での強度(例: オンセット/フラックス)合計が最大の位相を選ぶ。

    strength は拍単位配列。フレーズ境界が構造変化点に合う位相を選ぶ。
    """
    downbeats = np.asarray(downbeats, dtype=int)
    if len(downbeats) < bars_per_phrase:
        return None
    grids = [g for g in phrase_grids(downbeats, bars_options=(bars_per_phrase,))]
    if not grids:
        return None
    strength = np.asarray(strength, dtype=float)

    def score(g: PhraseGrid) -> float:
        idx = g.boundary_beats[(g.boundary_beats >= 0) & (g.boundary_beats < len(strength))]
        idx = idx[idx > 0]  # The file start has no preceding section to compare.
        return float(np.mean(strength[idx])) if idx.size else 0.0

    return max(grids, key=score)
