"""バックアップ／リストア（基本設計書 §11, §16 S5）。

書込前に master.db を含む必要ファイルを退避し、ハッシュで検証する。リストアは
rekordbox 停止時のみ許可する（フェイルクローズ）。
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..domain.enums import ErrorCode
from .errors import AdapterError

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    size_bytes: int
    sha256: str


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def create_backup(src_db: Path, backup_dir: Path, *, min_free_bytes: int = 200 * 1024 * 1024) -> BackupInfo:
    """master.db をバックアップし検証する。空き容量不足なら DISK_FULL。"""
    src_db = Path(src_db)
    backup_dir = Path(backup_dir)
    if not src_db.exists():
        raise AdapterError(ErrorCode.UNKNOWN_SCHEMA, f"バックアップ元が存在しません: {src_db}")
    backup_dir.mkdir(parents=True, exist_ok=True)

    free = shutil.disk_usage(str(backup_dir)).free
    if free < max(min_free_bytes, src_db.stat().st_size * 2):
        raise AdapterError(ErrorCode.DISK_FULL, "バックアップ用の空き容量が不足しています")

    dst = backup_dir / f"{src_db.stem}.backup{src_db.suffix}"
    shutil.copy2(src_db, dst)

    info = BackupInfo(path=dst, size_bytes=dst.stat().st_size, sha256=_sha256(dst))
    if info.size_bytes != src_db.stat().st_size:
        raise AdapterError(ErrorCode.COMMIT_FAILED, "バックアップの検証に失敗しました")
    return info


def restore_backup(backup: Path, dest_db: Path, *, rekordbox_running: bool) -> None:
    """バックアップを書き戻す。rekordbox 実行中は拒否する。"""
    if rekordbox_running:
        raise AdapterError(ErrorCode.RBX_RUNNING, "rekordbox 実行中はリストアできません")
    backup = Path(backup)
    if not backup.exists():
        raise AdapterError(ErrorCode.UNKNOWN_SCHEMA, f"バックアップが存在しません: {backup}")
    shutil.copy2(backup, dest_db)


def verify_backup(info: BackupInfo) -> bool:
    """バックアップの存在とハッシュ一致を確認する。"""
    return info.path.exists() and _sha256(info.path) == info.sha256
