from __future__ import annotations

CUE_LIMITS = {"MEMORY": 10, "HOT": 8}


def expand_cue_kind(kind: str) -> tuple[str, ...]:
    """利用者の選択を、書き出す個々のキュー種別に展開する。"""
    if kind == "BOTH":
        return ("MEMORY", "HOT")
    if kind in {"MEMORY", "HOT"}:
        return (kind,)
    raise ValueError(f"未対応のキュー種別: {kind}")
