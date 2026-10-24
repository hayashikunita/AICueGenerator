"""ドメイン型（pyrekordbox / numpy 非依存）。

解析コアの出力を上位層 (API/永続化) に渡すための純粋なデータ構造。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import BeatSource, CueType


@dataclass(frozen=True)
class Evidence:
    """信頼度の内訳（説明可能性の根拠）。"""

    name: str
    weight: float
    score: float  # 0..1 に正規化した各成分の達成度
    detail: str = ""

    @property
    def contribution(self) -> float:
        """信頼度(0..100)への寄与点。"""
        return self.weight * self.score


@dataclass(frozen=True)
class CueCandidate:
    """種類別のCue候補。time_sec は音源先頭からの秒。"""

    cue_type: CueType
    time_sec: float
    beat_index: int
    confidence: float  # 0..100
    rank: int
    evidence: tuple[Evidence, ...] = ()
    phrase_aligned: bool = False


@dataclass(frozen=True)
class BeatGrid:
    """ビートグリッド。beat_times は秒、downbeat_indices は beat_times の添字。"""

    bpm: float
    beat_times: tuple[float, ...]
    downbeat_indices: tuple[int, ...]
    source: BeatSource

    @property
    def beat_count(self) -> int:
        return len(self.beat_times)


@dataclass(frozen=True)
class PhraseSection:
    start_beat: int
    end_beat: int
    kind: str


@dataclass(frozen=True)
class AnalysisResult:
    """1曲分の解析結果。"""

    fingerprint: str
    duration_sec: float
    beatgrid: BeatGrid
    candidates: tuple[CueCandidate, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)
