"""書込計画の生成と実行（基本設計書 §11）。

- build_write_plan: 承認済み判断と既存Cueを突き合わせ、ADD/REPLACE/KEEP/SKIP/CONFLICT を
  決める純ロジック。confirmation_hash で dry-run と実行の同一性を保証する。
- execute_write_plan: 診断でフェイルクローズ。書込可でなければ WRITE_DISABLED を返す。
  実際の DjmdCue 書込は P0 スパイク合格・compat 許可後にのみ有効化する。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from ..common import dumps
from ..domain.enums import ErrorCode, WriteAction
from .diagnostics import DiagnosticsResult

# 同一 slot とみなす時間許容（ミリ秒）。この範囲の既存Cueは REPLACE 対象。
_MATCH_TOLERANCE_MS = 30


@dataclass(frozen=True)
class PlanItem:
    track_id: str
    cue_kind: str
    action: WriteAction
    time_ms: int
    slot: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str = ""


@dataclass(frozen=True)
class WritePlan:
    items: tuple[PlanItem, ...]
    confirmation_hash: str

    @property
    def add_count(self) -> int:
        return sum(1 for i in self.items if i.action is WriteAction.ADD)

    @property
    def replace_count(self) -> int:
        return sum(1 for i in self.items if i.action is WriteAction.REPLACE)

    @property
    def conflict_count(self) -> int:
        return sum(1 for i in self.items if i.action is WriteAction.CONFLICT)


def _hash_items(items: list[PlanItem]) -> str:
    payload = dumps(
        [
            [i.track_id, i.cue_kind, i.action.value, i.time_ms, i.slot]
            for i in sorted(items, key=lambda x: (x.track_id, x.cue_kind, x.time_ms))
        ]
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_write_plan(
    decisions: list[dict[str, Any]],
    existing_by_track: dict[str, list[dict[str, Any]]] | None = None,
) -> WritePlan:
    """承認済み判断から書込計画を生成する。

    decisions 要素: {track_id, cue_kind, time_ms, slot?, cue_type?}
    existing_by_track: track_id -> [{time_ms, cue_kind, slot?}]
    """
    existing_by_track = existing_by_track or {}
    items: list[PlanItem] = []

    # 同一トラック・種別・時刻の重複入力は CONFLICT にする。
    seen: dict[tuple[str, str, int], int] = {}

    for d in decisions:
        track_id = d["track_id"]
        cue_kind = d["cue_kind"]
        time_ms = int(d["time_ms"])
        slot = d.get("slot")
        key = (track_id, cue_kind, time_ms)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            items.append(
                PlanItem(track_id, cue_kind, WriteAction.CONFLICT, time_ms, slot,
                         reason="同一位置の重複指定")
            )
            continue

        existing = existing_by_track.get(track_id, [])
        match = _find_existing(existing, cue_kind, time_ms, slot)
        after = {"time_ms": time_ms, "cue_kind": cue_kind, "slot": slot}
        if match is None:
            items.append(PlanItem(track_id, cue_kind, WriteAction.ADD, time_ms, slot, after=after))
        elif int(match["time_ms"]) == time_ms:
            items.append(
                PlanItem(track_id, cue_kind, WriteAction.KEEP, time_ms, slot, before=match,
                         after=after, reason="既存と同一")
            )
        else:
            items.append(
                PlanItem(track_id, cue_kind, WriteAction.REPLACE, time_ms, slot, before=match,
                         after=after, reason="既存Cueを更新")
            )

    return WritePlan(items=tuple(items), confirmation_hash=_hash_items(items))


def _find_existing(
    existing: list[dict[str, Any]], cue_kind: str, time_ms: int, slot: str | None
) -> dict[str, Any] | None:
    candidates = [e for e in existing if e.get("cue_kind") == cue_kind]
    if slot is not None:
        for e in candidates:
            if e.get("slot") == slot:
                return e
    for e in candidates:
        if abs(int(e["time_ms"]) - time_ms) <= _MATCH_TOLERANCE_MS:
            return e
    return None


@dataclass
class ExecuteResult:
    ok: bool
    error_code: ErrorCode | None = None
    message: str = ""
    written: int = 0
    details: dict[str, Any] = field(default_factory=dict)


def execute_write_plan(
    plan: WritePlan,
    *,
    confirmation_hash: str,
    diagnostics: DiagnosticsResult,
) -> ExecuteResult:
    """書込を実行する。安全条件を満たさない場合は書込せず理由を返す。"""
    if confirmation_hash != plan.confirmation_hash:
        return ExecuteResult(False, ErrorCode.PLAN_HASH_MISMATCH,
                             "確認ハッシュが一致しません（計画が変化した可能性）")
    if plan.conflict_count > 0:
        return ExecuteResult(False, ErrorCode.WRITE_DISABLED,
                             "衝突する項目があるため実行できません",
                             details={"conflicts": plan.conflict_count})
    if not diagnostics.writable:
        return ExecuteResult(
            False,
            ErrorCode.WRITE_DISABLED,
            "現在の環境では書込が許可されていません（read-only）",
            details={"reasons": diagnostics.reasons},
        )
    # ここに到達するのは P0 合格＋compat 許可後のみ。実書込は writer 実装で有効化する。
    return ExecuteResult(
        False,
        ErrorCode.WRITE_DISABLED,
        "実書込は P0 スパイク合格後に有効化されます",
        details={"planned": len(plan.items)},
    )
