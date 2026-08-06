r"""P0 スパイク検証ハーネス (基本設計書 §16, S1-S9)。

rekordbox master.db の **コピー** に対してのみ実行すること。
書込検査 (S2/S3/S6) は既定で無効。--allow-write と全安全条件を満たした場合のみ実行する。

使い方 (backend ディレクトリで):
    .\.venv\Scripts\python.exe -m spikes.p0_spike \
        --db "C:\\path\\to\\COPY\\master.db" \
        --backup-dir "C:\\path\\to\\backups" \
        --json report.json

書込まで検査する場合 (rekordbox 終了・コピー確認後):
    ... --allow-write --content-id <ContentID>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# パッケージ外実行でも app を解決できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rekordbox.adapter import open_database, read_schema  # noqa: E402
from app.rekordbox.compat import schema_fingerprint  # noqa: E402
from app.rekordbox.diagnostics import diagnose, get_rekordbox_pid  # noqa: E402
from app.rekordbox.reader import (  # noqa: E402
    get_cues,
    list_playlists,
    read_beatgrid,
    read_phrases,
)

BLOCKER = "Blocker"
MAJOR = "Major"
MINOR = "Minor"

PASS = "pass"
FAIL = "fail"
SKIP = "skip"
MANUAL = "manual"


@dataclass
class Check:
    id: str
    name: str
    severity: str
    status: str = SKIP
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _live_db_path() -> Path | None:
    try:
        from pyrekordbox.config import get_config

        p = get_config("rekordbox6", "db_path") or get_config("rekordbox7", "db_path")
        return Path(p).resolve() if p else None
    except Exception:  # noqa: BLE001
        return None


def _write_guard(db_path: Path, allow_write: bool) -> tuple[bool, str]:
    """書込を許可してよいかを判定する。安全側フェイルクローズ。"""
    if not allow_write:
        return False, "--allow-write 未指定"
    pid = get_rekordbox_pid()
    if pid is not None:
        return False, f"rekordbox 実行中 (pid={pid})"
    live = _live_db_path()
    if live is not None and db_path.resolve() == live:
        return False, "対象が本番 master.db (コピーを指定してください)"
    return True, "ok"


def _pick_content(db: Any, content_id: str | None) -> Any | None:
    try:
        if content_id is not None:
            return db.get_content(ID=content_id).one_or_none()
        return db.get_content().first()
    except Exception:  # noqa: BLE001
        return None


# --- 個別チェック -----------------------------------------------------------


def check_s1_open(db: Any) -> Check:
    c = Check("S1", "鍵取得と復号オープン", BLOCKER)
    try:
        n = db.get_content().count()
        c.status = PASS
        c.detail = f"復号オープン成功。曲数={n}"
        c.data = {"content_count": n}
    except Exception as exc:  # noqa: BLE001
        c.status = FAIL
        c.detail = f"読取失敗: {exc}"
    return c


def check_s9_compat(db: Any) -> Check:
    c = Check("S9", "バージョン×スキーマ互換", BLOCKER)
    try:
        import pyrekordbox

        schema = read_schema(db)
        fp = schema_fingerprint(schema)
        c.status = PASS
        c.detail = f"pyrekordbox={pyrekordbox.__version__}, tables={len(schema)}"
        c.data = {
            "pyrekordbox_version": pyrekordbox.__version__,
            "schema_fingerprint": fp,
            "table_count": len(schema),
        }
    except Exception as exc:  # noqa: BLE001
        c.status = FAIL
        c.detail = f"スキーマ取得失敗: {exc}"
    return c


def check_s5_backup(db_path: Path, backup_dir: Path | None) -> Check:
    c = Check("S5", "バックアップ／リストア", BLOCKER)
    if backup_dir is None:
        c.status = SKIP
        c.detail = "--backup-dir 未指定"
        return c
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        dst = backup_dir / f"{db_path.stem}.spike-backup{db_path.suffix}"
        shutil.copy2(db_path, dst)
        ok = dst.exists() and dst.stat().st_size == db_path.stat().st_size
        free = shutil.disk_usage(str(backup_dir)).free
        c.status = PASS if ok else FAIL
        c.detail = f"バックアップ作成={ok}, 空き={free // (1024*1024)}MiB"
        c.data = {"backup_path": str(dst), "free_bytes": free, "verified": ok}
    except Exception as exc:  # noqa: BLE001
        c.status = FAIL
        c.detail = f"バックアップ失敗: {exc}"
    return c


def check_s7_beatgrid(db: Any, content: Any) -> Check:
    c = Check("S7", "PQTZ ビートグリッド読取", MAJOR)
    if content is None:
        c.status = SKIP
        c.detail = "対象曲なし"
        return c
    info = read_beatgrid(db, content)
    c.data = info
    if info.get("available"):
        c.status = PASS
        c.detail = f"beats={info['beat_count']}, downbeats={info['downbeat_count']}"
    else:
        c.status = FAIL
        c.detail = "PQTZ を読めませんでした"
    return c


def check_s8_phrases(db: Any, content: Any) -> Check:
    c = Check("S8", "PSSI フレーズ読取", MINOR)
    if content is None:
        c.status = SKIP
        c.detail = "対象曲なし"
        return c
    info = read_phrases(db, content)
    c.data = info
    if info.get("available"):
        c.status = PASS
        c.detail = f"phrases={info['phrase_count']}, mood={info.get('mood')}"
    else:
        c.status = FAIL
        c.detail = "PSSI を読めませんでした (フォールバック解析で代替可)"
    return c


def check_s4_time_accuracy(db: Any, content: Any) -> Check:
    c = Check("S4", "CBR/VBR/AAC 時間精度", MAJOR)
    if content is None:
        c.status = SKIP
        c.detail = "対象曲なし"
        return c
    fmt = getattr(content, "FileType", None)
    length = getattr(content, "Length", None)
    bpm = getattr(content, "BPM", None)
    c.status = MANUAL
    c.detail = (
        f"format={fmt}, length={length}s, bpm={bpm}: "
        "実測 msec とのズレ検証は手動 (代表 VBR/AAC で ±数十 ms 確認)"
    )
    c.data = {"file_type": fmt, "length_sec": length, "bpm": bpm}
    return c


def _write_memory_cue(db: Any, content: Any, in_msec: int, comment: str) -> dict[str, Any]:
    from pyrekordbox.db6.tables import DjmdCue

    cue_id = db.generate_unused_id(DjmdCue)
    usn = db.increment_local_usn()
    cue = DjmdCue.create(
        ID=str(cue_id),
        ContentID=getattr(content, "ID", None),
        InMsec=int(in_msec),
        InFrame=0,
        Kind=0,
        Color=-1,
        Comment=comment,
        ContentUUID=getattr(content, "UUID", None),
        UUID=str(uuid.uuid4()),
        rb_local_usn=usn,
    )
    db.add(cue)
    db.flush()
    return {"cue_id": str(cue_id), "usn_after": usn}


def check_s2_s3_s6_write(db: Any, content: Any, comment: str) -> list[Check]:
    s2 = Check("S2", "DB のみ書込→再起動後反映", BLOCKER)
    s3 = Check("S3", "USN／同期メタ整合", BLOCKER)
    s6 = Check("S6", "トランザクション／ロールバック", MAJOR)

    if content is None:
        for c in (s2, s3, s6):
            c.status = SKIP
            c.detail = "対象曲なし"
        return [s2, s3, s6]

    # --- S6: ロールバックが効くこと ---
    try:
        before = get_cues(db, getattr(content, "ID", None))
        usn0 = db.get_local_usn()
        _write_memory_cue(db, content, in_msec=1000, comment=comment + "_ROLLBACK")
        db.rollback()
        after = get_cues(db, getattr(content, "ID", None))
        usn1 = db.get_local_usn()
        if len(after) == len(before):
            s6.status = PASS
            s6.detail = f"ロールバックで未反映 (cues {len(before)}→{len(after)})"
        else:
            s6.status = FAIL
            s6.detail = f"ロールバック後も残存 (cues {len(before)}→{len(after)})"
        s6.data = {"usn_before": usn0, "usn_after_rollback": usn1}
    except Exception as exc:  # noqa: BLE001
        s6.status = FAIL
        s6.detail = f"例外: {exc}"

    # --- S2/S3: コミット→USN 増加・キュー反映 ---
    try:
        usn_before = db.get_local_usn()
        before = get_cues(db, getattr(content, "ID", None))
        info = _write_memory_cue(db, content, in_msec=2000, comment=comment)
        db.commit()
        usn_after = db.get_local_usn()
        after = get_cues(db, getattr(content, "ID", None))
        added = len(after) - len(before)

        if added >= 1:
            s2.status = MANUAL
            s2.detail = (
                f"DB へ書込成功 (cues {len(before)}→{len(after)})。"
                "★要手動: rekordbox 再起動後にこのキューが表示されるか確認 (S2 の合否)"
            )
        else:
            s2.status = FAIL
            s2.detail = "コミット後もキューが増えていない"
        s2.data = {"added": added, **info}

        if usn_after > usn_before:
            s3.status = PASS
            s3.detail = f"local_usn {usn_before}→{usn_after} に増加"
        else:
            s3.status = FAIL
            s3.detail = f"USN 未増加 ({usn_before}→{usn_after})"
        s3.data = {"usn_before": usn_before, "usn_after": usn_after}
    except Exception as exc:  # noqa: BLE001
        s2.status = FAIL
        s2.detail = f"例外: {exc}\n{traceback.format_exc(limit=2)}"
        s3.status = FAIL
        s3.detail = "書込失敗のため判定不能"

    return [s2, s3, s6]


# --- オーケストレーション ----------------------------------------------------


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).resolve()
    backup_dir = Path(args.backup_dir).resolve() if args.backup_dir else None
    can_write, write_reason = _write_guard(db_path, args.allow_write)

    checks: list[Check] = []
    # DB を開かない検査 (S5) は先に。
    checks.append(check_s5_backup(db_path, backup_dir))

    diag = diagnose(backup_dir=backup_dir)

    with open_database(db_path) as db:
        content = _pick_content(db, args.content_id)
        checks.append(check_s1_open(db))
        checks.append(check_s9_compat(db))
        checks.append(check_s4_time_accuracy(db, content))
        checks.append(check_s7_beatgrid(db, content))
        checks.append(check_s8_phrases(db, content))
        if can_write:
            checks.extend(check_s2_s3_s6_write(db, content, comment="AICUE_SPIKE"))
        else:
            for cid, name, sev in (
                ("S2", "DB のみ書込→再起動後反映", BLOCKER),
                ("S3", "USN／同期メタ整合", BLOCKER),
                ("S6", "トランザクション／ロールバック", MAJOR),
            ):
                checks.append(
                    Check(cid, name, sev, status=SKIP, detail=f"書込無効: {write_reason}")
                )

    checks.sort(key=lambda c: c.id)
    blocker_fail = any(c.severity == BLOCKER and c.status == FAIL for c in checks)
    verdict = "NO-GO" if blocker_fail else "GO (要手動確認項目あり)"

    return {
        "db_path": str(db_path),
        "write_enabled": can_write,
        "write_reason": write_reason,
        "diagnostics": diag.to_dict(),
        "verdict": verdict,
        "checks": [asdict(c) for c in checks],
    }


def _print_report(report: dict[str, Any]) -> None:
    print("=" * 72)
    print(f"P0 スパイク結果: {report['verdict']}")
    print(f"DB: {report['db_path']}")
    print(f"書込: {'有効' if report['write_enabled'] else '無効'} ({report['write_reason']})")
    print("-" * 72)
    print(f"{'ID':<4}{'重要度':<9}{'状態':<8}{'項目'}")
    for c in report["checks"]:
        print(f"{c['id']:<4}{c['severity']:<9}{c['status']:<8}{c['name']}")
        if c["detail"]:
            print(f"      └ {c['detail']}")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rekordbox P0 スパイク (S1-S9)")
    parser.add_argument("--db", required=True, help="master.db の【コピー】へのパス")
    parser.add_argument("--backup-dir", default=None, help="S5 バックアップ先")
    parser.add_argument("--content-id", default=None, help="検査対象 ContentID (省略=先頭曲)")
    parser.add_argument("--allow-write", action="store_true", help="S2/S3/S6 書込検査を有効化")
    parser.add_argument("--json", default=None, help="レポート JSON 出力先")
    args = parser.parse_args(argv)

    try:
        report = run(args)
    except Exception as exc:  # noqa: BLE001
        print(f"スパイク実行失敗: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2

    _print_report(report)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON: {args.json}")

    return 1 if report["verdict"].startswith("NO-GO") else 0


if __name__ == "__main__":
    raise SystemExit(main())
