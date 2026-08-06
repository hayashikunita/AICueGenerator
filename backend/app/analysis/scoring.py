"""信頼度算出（基本設計書 §9.3, 要件 §7.4）。

初期重み: ビート安定性20 / フレーズ整合20 / エネルギー差25 / 打楽器・onset差20 / 反復整合15。
PSSI が候補種別と整合する場合はフレーズ整合成分に加点（上限内でクリップ）。
"""

from __future__ import annotations

from ..domain.models import Evidence

# 重みは engine_version / params_json に紐づけてバージョン管理する（§9.3）。
DEFAULT_WEIGHTS: dict[str, float] = {
    "beat_stability": 20.0,
    "phrase_alignment": 20.0,
    "energy_diff": 25.0,
    "percussive_onset": 20.0,
    "repetition": 15.0,
}

# しきい値（§9.3）
HIGH_CONFIDENCE = 80.0
REVIEW_CONFIDENCE = 60.0

_LABELS = {
    "beat_stability": "ビート安定性",
    "phrase_alignment": "フレーズ整合",
    "energy_diff": "エネルギー差",
    "percussive_onset": "打楽器・onset差",
    "repetition": "反復整合",
}


def score_candidate(
    components: dict[str, float],
    *,
    pssi_bonus: float = 0.0,
    weights: dict[str, float] | None = None,
) -> tuple[float, tuple[Evidence, ...]]:
    """成分スコア(各0..1)から信頼度(0..100)と根拠を算出する。

    pssi_bonus はフレーズ整合成分へ 0..1 の範囲で加点（クリップ）する。
    """
    w = weights or DEFAULT_WEIGHTS
    evidence: list[Evidence] = []
    total = 0.0
    for key, weight in w.items():
        raw = float(components.get(key, 0.0))
        if key == "phrase_alignment":
            raw = min(1.0, raw + max(0.0, pssi_bonus))
        s = _clip01(raw)
        detail = "PSSI整合で加点" if key == "phrase_alignment" and pssi_bonus > 0 else ""
        evidence.append(Evidence(name=_LABELS.get(key, key), weight=weight, score=s, detail=detail))
        total += weight * s
    return round(total, 2), tuple(evidence)


def confidence_band(confidence: float) -> str:
    """信頼度を high / review / reject に分類する。"""
    if confidence >= HIGH_CONFIDENCE:
        return "high"
    if confidence >= REVIEW_CONFIDENCE:
        return "review"
    return "reject"


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
