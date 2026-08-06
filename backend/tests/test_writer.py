from __future__ import annotations

from app.domain.enums import ErrorCode, WriteAction
from app.rekordbox.diagnostics import DiagnosticsResult
from app.rekordbox.writer import build_write_plan, execute_write_plan


def _writable_diag(writable: bool) -> DiagnosticsResult:
    return DiagnosticsResult(
        rekordbox_running=not writable,
        rekordbox_pid=None if writable else 1,
        sqlcipher_available=True,
        schema_fingerprint="sha256:x",
        schema_supported=writable,
        integrity_ok=True,
        free_bytes=10**9,
        writable=writable,
        reasons=[] if writable else ["rekordbox 実行中"],
    )


def test_plan_add_when_no_existing():
    plan = build_write_plan(
        [{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000}],
    )
    assert plan.add_count == 1
    assert plan.items[0].action is WriteAction.ADD


def test_plan_replace_and_keep():
    # KEEP: 同一種別・同一時刻の既存はそのまま。
    keep_existing = {"T1": [{"time_ms": 1000, "cue_kind": "MEMORY", "slot": None}]}
    keep = build_write_plan([{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000}], keep_existing)
    assert keep.items[0].action is WriteAction.KEEP

    # REPLACE(slot): 同一 HOT スロットで時刻が変われば置換。
    slot_existing = {"T1": [{"time_ms": 1000, "cue_kind": "HOT", "slot": "A"}]}
    replace = build_write_plan(
        [{"track_id": "T1", "cue_kind": "HOT", "time_ms": 5000, "slot": "A"}], slot_existing
    )
    assert replace.items[0].action is WriteAction.REPLACE

    # REPLACE(近接): 許容内(±30ms)のズレは既存の更新とみなす。
    near_existing = {"T1": [{"time_ms": 1000, "cue_kind": "MEMORY", "slot": None}]}
    near = build_write_plan([{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1020}], near_existing)
    assert near.items[0].action is WriteAction.REPLACE


def test_plan_conflict_on_duplicate():
    plan = build_write_plan(
        [
            {"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000},
            {"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000},
        ]
    )
    assert plan.conflict_count == 1


def test_confirmation_hash_is_stable():
    a = build_write_plan([{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000}])
    b = build_write_plan([{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000}])
    assert a.confirmation_hash == b.confirmation_hash


def test_execute_blocks_on_hash_mismatch():
    plan = build_write_plan([{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000}])
    res = execute_write_plan(plan, confirmation_hash="sha256:wrong", diagnostics=_writable_diag(True))
    assert not res.ok and res.error_code is ErrorCode.PLAN_HASH_MISMATCH


def test_execute_blocks_when_not_writable():
    plan = build_write_plan([{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000}])
    res = execute_write_plan(
        plan, confirmation_hash=plan.confirmation_hash, diagnostics=_writable_diag(False)
    )
    assert not res.ok and res.error_code is ErrorCode.WRITE_DISABLED


def test_execute_writable_still_gated_until_p0():
    plan = build_write_plan([{"track_id": "T1", "cue_kind": "MEMORY", "time_ms": 1000}])
    res = execute_write_plan(
        plan, confirmation_hash=plan.confirmation_hash, diagnostics=_writable_diag(True)
    )
    # P0 合格前は書込機能は未有効化（フェイルクローズ）。
    assert not res.ok and res.error_code is ErrorCode.WRITE_DISABLED
