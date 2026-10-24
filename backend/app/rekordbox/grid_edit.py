"""Explicit, per-track downbeat edits. Database connections remain read-only.

Patch documented beat-number fields in place; never rebuild ANLZ files, since
that can discard unknown tags or alter cue/phrase/waveform payloads.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class GridEditError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sections(data: bytes):
    if len(data) < 28 or data[:4] != b"PMAI":
        raise GridEditError("未対応の解析ファイルです。保存を中止しました。")
    header, size = struct.unpack_from(">II", data, 4)
    if not 28 <= header <= len(data) or size != len(data):
        raise GridEditError("解析ファイルの長さが不正です。保存を中止しました。")
    pos = header
    while pos < size:
        if pos + 12 > size:
            raise GridEditError("解析ファイルのタグが壊れています。")
        kind, head, length = struct.unpack_from(">4sII", data, pos)
        if not 12 <= head <= length or pos + length > size:
            raise GridEditError("解析ファイルのタグ長が不正です。")
        yield kind, pos, head, length
        pos += length


def ticks(data: bytes) -> tuple[tuple[int, int, int], ...] | None:
    grids = []
    for kind, pos, head, length in sections(data):
        if kind != b"PQTZ":
            continue
        if head != 24 or struct.unpack_from(">I", data, pos + 16)[0] != 0x80000:
            raise GridEditError("未対応のビートグリッド形式です。")
        count = struct.unpack_from(">I", data, pos + 20)[0]
        if count < 4 or length != head + 8 * count:
            raise GridEditError("ビートグリッドの件数が不正です。")
        grid = tuple(struct.unpack_from(">HHI", data, pos + head + i * 8) for i in range(count))
        if any(not 1 <= b <= 4 or bpm <= 0 for b, bpm, _ in grid):
            raise GridEditError("4/4拍子のグリッドだけを保存できます。")
        if any(a[2] >= b[2] for a, b in zip(grid, grid[1:])):
            raise GridEditError("拍の時刻が不正です。")
        grids.append(grid)
    if len(grids) > 1:
        raise GridEditError("複数のグリッドがあるため保存を中止しました。")
    return grids[0] if grids else None


def patch_grid(data: bytes, first_beat: int, grid: tuple[tuple[int, int, int], ...]) -> bytes:
    """Make the current numbered first_beat the new beat 1, across the track.

    PQT2's opaque two-byte entries are NOT bar numbers; keep them unchanged.
    Only its two documented first/last beat anchors carry bar numbers.
    """
    if first_beat not in (1, 2, 3, 4):
        raise GridEditError("1〜4拍目から選んでください。")
    own_grid = ticks(data)
    if own_grid is not None and own_grid != grid:
        raise GridEditError("解析ファイル間でグリッドが一致しません。rekordbox で確認してください。")
    out = bytearray(data)
    for kind, pos, head, length in sections(data):
        offsets = []
        if kind == b"PQTZ":
            offsets = [pos + head + i * 8 for i in range(len(grid))]
        elif kind == b"PQT2":
            if head != 56 or struct.unpack_from(">I", data, pos + 16)[0] != 0x01000002:
                raise GridEditError("未対応の拡張グリッド形式です。")
            count = struct.unpack_from(">I", data, pos + 40)[0]
            if count not in (0, len(grid)) or length != head + count * 2:
                raise GridEditError("拡張グリッドの件数が一致しません。")
            anchors = [struct.unpack_from(">HHI", data, pos + offset) for offset in (24, 32)]
            if anchors != [grid[0], grid[-1]]:
                raise GridEditError("拡張グリッドの先頭・末尾が一致しません。保存を中止しました。")
            offsets = [pos + 24, pos + 32]
        for offset in offsets:
            old = struct.unpack_from(">H", data, offset)[0]
            struct.pack_into(">H", out, offset, (old - first_beat) % 4 + 1)
    return bytes(out)


def save_block_reason() -> str | None:
    """Fail closed if process inspection is unavailable or incomplete."""
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name")
            if not name:
                return "プロセスの状態を確認できません。保存を中止しました。"
            if "rekordbox" in name.casefold():
                return "保存するには rekordbox を終了してください。終了後に変更内容を再確認してください。"
    except Exception:
        return "rekordbox の終了を確認できません。psutil とプロセスへのアクセス権を確認してください。"
    return None


@dataclass(frozen=True)
class Snapshot:
    content_id: str
    title: str
    audio_path: str
    files: dict[Path, bytes]
    grid: tuple[tuple[int, int, int], ...]


def snapshot(db: Any, content_id: str, expected_path: str) -> Snapshot:
    content = db.get_content(ID=content_id)
    if content is None or Path(str(content.FolderPath)).resolve() != Path(expected_path).resolve():
        raise GridEditError("選択中の曲と登録パスが一致しません。曲を選び直してください。")
    paths = db.get_anlz_paths(content)
    files = {}
    for value in paths.values():
        if not value:
            continue
        path = Path(value).absolute()
        if path.suffix.upper() not in (".DAT", ".EXT", ".2EX") or path.is_symlink():
            raise GridEditError("未対応の解析ファイルの配置です。")
        if path.stat().st_size > 64 * 1024 * 1024:
            raise GridEditError("解析ファイルが大きすぎるため保存を中止しました。")
        files[path] = path.read_bytes()
    grids = [grid for data in files.values() if (grid := ticks(data)) is not None]
    if not grids or any(grid != grids[0] for grid in grids):
        raise GridEditError("有効な解析済みグリッドを確認できません。")
    snap = Snapshot(str(content.ID), content.Title or "(無題)", str(content.FolderPath), files, grids[0])
    # Validate every companion file, including PQT2 anchors, before offering edits.
    for data in files.values():
        patch_grid(data, 1, snap.grid)
    return snap


def preview(snap: Snapshot, first_beat: int = 1) -> dict:
    return {
        "content_id": snap.content_id, "title": snap.title, "path": snap.audio_path,
        "first_beat": first_beat, "beat_count": len(snap.grid),
        "beats": [{"time_ms": ms, "before": beat, "after": (beat - first_beat) % 4 + 1}
                  for beat, _, ms in snap.grid[:8]],
        "blocked_reason": save_block_reason(),
    }


@dataclass(frozen=True)
class Plan:
    snapshot: Snapshot
    first_beat: int
    expires_at: float


_lock = threading.Lock()
_plans: dict[str, Plan] = {}


def make_plan(snap: Snapshot, first_beat: int) -> dict:
    if first_beat not in (2, 3, 4):
        raise GridEditError("現在と異なる小節頭を選んでください。")
    for data in snap.files.values():
        patch_grid(data, first_beat, snap.grid)
    result = preview(snap, first_beat)
    with _lock:
        now = time.time()
        for key in list(_plans):
            if _plans[key].expires_at <= now:
                del _plans[key]
        if len(_plans) >= 32:
            del _plans[next(iter(_plans))]
        plan_id = uuid.uuid4().hex
        _plans[plan_id] = Plan(snap, first_beat, now + 600)
    return {**result, "plan_id": plan_id, "expires_in": 600}


def _assert_stopped():
    if reason := save_block_reason():
        raise GridEditError(reason)


def _stage(path: Path, data: bytes) -> Path:
    with tempfile.NamedTemporaryFile(prefix=".aicue-grid-", suffix=".tmp", dir=path.parent, delete=False) as file:
        temp_path = Path(file.name)
        try:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    return temp_path


def _write_backup(path: Path, data: bytes):
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def _write_manifest(path: Path, manifest: dict):
    with path.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())


def apply_plan(db: Any, content_id: str, plan_id: str, backup_root: Path) -> dict:
    with _lock:
        plan = _plans.get(plan_id)
        if plan is None or plan.expires_at <= time.time() or plan.snapshot.content_id != content_id:
            raise GridEditError("確認内容の有効期限が切れました。変更内容を再確認してください。")
        _assert_stopped()
        before = plan.snapshot
        current = snapshot(db, content_id, before.audio_path)
        if current.files != before.files or current.title != before.title:
            raise GridEditError("確認後に解析データが変わりました。変更内容を再確認してください。")
        changes = {path: patch_grid(data, plan.first_beat, before.grid) for path, data in before.files.items()}
        changes = {path: data for path, data in changes.items() if data != before.files[path]}
        backup_dir = backup_root / plan_id
        backup_dir.mkdir(parents=True, exist_ok=False)
        manifest = {"content_id": content_id, "title": before.title, "first_beat": plan.first_beat,
                    "status": "prepared", "files": []}
        staged = {}
        written = []
        try:
            for i, (path, data) in enumerate(changes.items()):
                backup = backup_dir / f"{i}-{path.name}"
                _write_backup(backup, before.files[path])
                if backup.read_bytes() != before.files[path]:
                    raise GridEditError("バックアップの検証に失敗しました。")
                manifest["files"].append({"original": str(path), "backup": backup.name,
                                          "before_sha256": digest(before.files[path]), "after_sha256": digest(data)})
                staged[path] = _stage(path, data)
            manifest_path = backup_dir / "manifest.json"
            _write_manifest(manifest_path, manifest)
            _assert_stopped()
            # Check ALL analysis files again after preparing backups and staging.
            if snapshot(db, content_id, before.audio_path).files != before.files:
                raise GridEditError("保存前に解析データが変わりました。変更内容を再確認してください。")
            for path, temp_path in staged.items():
                _assert_stopped()
                if path.read_bytes() != before.files[path]:
                    raise GridEditError("保存中に解析データが変わりました。")
                os.replace(temp_path, path)
                written.append(path)
                if path.read_bytes() != changes[path]:
                    raise GridEditError("保存後の検証に失敗しました。")
            manifest["status"] = "saved"
            _write_manifest(manifest_path, manifest)
        except Exception as exc:
            failures = []
            for path in reversed(written):
                try:
                    if path.read_bytes() != changes[path]:
                        raise GridEditError("外部から変更されています")
                    restored = _stage(path, before.files[path])
                    try:
                        os.replace(restored, path)
                    finally:
                        restored.unlink(missing_ok=True)
                    if path.read_bytes() != before.files[path]:
                        raise GridEditError("復元の検証に失敗しました")
                except Exception:
                    failures.append(str(path))
            manifest["status"] = "restore_required" if failures else "rolled_back"
            manifest["restore_required"] = failures
            try:
                _write_manifest(backup_dir / "manifest.json", manifest)
            except OSError:
                # Recovery instructions must survive even if the backup volume is full.
                pass
            finally:
                _plans.pop(plan_id, None)
            if failures:
                raise GridEditError(f"保存に失敗し、復元が必要です。rekordbox を起動せず、バックアップを確認してください: {backup_dir}") from exc
            reason = str(exc) if isinstance(exc, GridEditError) else "解析ファイルの書き込みに失敗しました。"
            raise GridEditError(f"{reason} 変更済みのファイルは元に戻しました。変更内容を再確認してください。") from exc
        finally:
            for path in staged.values():
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        _plans.pop(plan_id, None)
        return {"ok": True, "backup_dir": str(backup_dir), "changed_files": len(changes),
                "message": "小節頭を保存しました。rekordbox を起動して曲を読み込み直してください。"}
