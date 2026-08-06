from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .adapter import read_schema
from .compat import DEFAULT_MATRIX, CompatMatrix, schema_fingerprint
from .dbkey import sqlcipher_available


def get_rekordbox_pid() -> int | None:
    """rekordbox プロセスの PID。実行中でなければ None。"""
    try:
        from pyrekordbox.utils import get_rekordbox_pid as _get_pid
    except Exception:  # noqa: BLE001 - 検出不能時は不明扱い
        return None
    try:
        pid = _get_pid()
    except Exception:  # noqa: BLE001
        return None
    return int(pid) if pid else None


@dataclass
class DiagnosticsResult:
    """書込可否判定の根拠 (基本設計書 §10.3 / §16)。"""

    rekordbox_running: bool
    rekordbox_pid: int | None
    sqlcipher_available: bool
    schema_fingerprint: str | None
    schema_supported: bool
    integrity_ok: bool | None
    free_bytes: int | None
    writable: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _integrity_ok(db: Any) -> bool | None:
    try:
        with db.engine.connect() as conn:
            row = conn.exec_driver_sql("PRAGMA integrity_check").fetchone()
    except Exception:  # noqa: BLE001 - 実行不能なら不明
        return None
    return bool(row) and str(row[0]).lower() == "ok"


def diagnose(
    db: Any | None = None,
    *,
    backup_dir: str | Path | None = None,
    matrix: CompatMatrix = DEFAULT_MATRIX,
    min_free_bytes: int = 200 * 1024 * 1024,
) -> DiagnosticsResult:
    """環境診断を行い書込可否を判定する。

    db を渡すとスキーマ指紋・整合性チェックまで行う。
    書込は「全条件を満たす場合のみ」許可する (安全側フェイルクローズ)。
    """
    reasons: list[str] = []

    pid = get_rekordbox_pid()
    running = pid is not None
    if running:
        reasons.append("rekordbox が実行中のため書込不可")

    cipher = sqlcipher_available()
    if not cipher:
        reasons.append("sqlcipher3 が無く復号不可")

    schema_fp: str | None = None
    schema_supported = False
    integrity: bool | None = None
    if db is not None:
        try:
            schema_fp = schema_fingerprint(read_schema(db))
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"スキーマ取得失敗: {exc}")
        else:
            schema_supported = matrix.is_supported(schema_fp)
            if not schema_supported:
                reasons.append("未知スキーマ (許可リスト外) のため書込不可")
        integrity = _integrity_ok(db)
        if integrity is False:
            reasons.append("DB 整合性チェックに失敗")

    free_bytes: int | None = None
    if backup_dir is not None:
        try:
            free_bytes = shutil.disk_usage(str(backup_dir)).free
        except Exception:  # noqa: BLE001
            free_bytes = None
        if free_bytes is not None and free_bytes < min_free_bytes:
            reasons.append("バックアップ用空き容量が不足")

    writable = (
        not running
        and cipher
        and schema_supported
        and integrity is not False
        and (free_bytes is None or free_bytes >= min_free_bytes)
    )

    return DiagnosticsResult(
        rekordbox_running=running,
        rekordbox_pid=pid,
        sqlcipher_available=cipher,
        schema_fingerprint=schema_fp,
        schema_supported=schema_supported,
        integrity_ok=integrity,
        free_bytes=free_bytes,
        writable=writable,
        reasons=reasons,
    )
