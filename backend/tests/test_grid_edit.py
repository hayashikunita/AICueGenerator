from __future__ import annotations

import json
import struct
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import routes_rekordbox
from app.main import app
from app.rekordbox import grid_edit as edit


def tag(kind, head, extra=b"", body=b""):
    assert len(extra) == head - 12
    return struct.pack(">4sII", kind, head, head + len(body)) + extra + body


def anlz(*tags):
    body = b"".join(tags)
    return struct.pack(">4sII", b"PMAI", 28, 28 + len(body)) + bytes(range(16)) + body


@pytest.fixture
def library(tmp_path, monkeypatch):
    grid = tuple(((i + 2) % 4 + 1, 12800 if i < 8 else 12750, 137 + i * 469 + i // 7) for i in range(16))
    pqtz = tag(b"PQTZ", 24, struct.pack(">III", 0, 0x80000, len(grid)), b"".join(struct.pack(">HHI", *g) for g in grid))
    anchors = b"".join(struct.pack(">HHI", *g) for g in (grid[0], grid[-1]))
    pqt2 = tag(b"PQT2", 56, struct.pack(">III", 0, 0x01000002, 0) + anchors + struct.pack(">IIII", len(grid), 7, 8, 9), bytes(range(32)))
    # Include opaque cue, phrase, waveform and unknown future payloads. None may change.
    opaque = [tag(k, 12, body=bytes(range(64))) for k in (b"PCOB", b"PCO2", b"PSSI", b"PWV5", b"NEW!")]
    files = {tmp_path / "ANLZ0000.DAT": anlz(pqtz, *opaque),
             tmp_path / "ANLZ0000.EXT": anlz(*opaque, pqt2),
             tmp_path / "ANLZ0000.2EX": anlz(*opaque)}
    for path, data in files.items():
        path.write_bytes(data)
    content = SimpleNamespace(ID="test-track", Title="Only this track", FolderPath=str(tmp_path / "song.wav"))
    db = SimpleNamespace(get_content=lambda **kw: content if kw.get("ID") == content.ID else None,
                         get_anlz_paths=lambda c: {p.suffix[1:]: p for p in files})
    monkeypatch.setattr(edit, "save_block_reason", lambda: None)
    @contextmanager
    def open_library(**kwargs):
        yield db
    monkeypatch.setattr(routes_rekordbox, "open_rekordbox", open_library)
    return db, content, files, grid


def snap(library):
    db, content, _, _ = library
    return edit.snapshot(db, content.ID, content.FolderPath)


@pytest.mark.parametrize("first", [1, 2, 3, 4])
def test_binary_patch_changes_only_documented_bar_numbers(library, first):
    _, _, files, grid = library
    for path, data in files.items():
        result = edit.patch_grid(data, first, grid)
        allowed = set()
        for kind, pos, head, length in edit.sections(data):
            if kind == b"PQTZ":
                allowed.update(pos + head + i * 8 + 1 for i in range(len(grid)))
            elif kind == b"PQT2":
                allowed.update((pos + 25, pos + 33))
                assert result[pos + head:pos + length] == data[pos + head:pos + length]
            else:
                assert result[pos:pos + length] == data[pos:pos + length]
        changed = {i for i, (a, b) in enumerate(zip(data, result)) if a != b}
        assert changed <= allowed and len(result) == len(data)
        assert edit.patch_grid(result, (1 - first) % 4 + 1, tuple(((b - first) % 4 + 1, bpm, t) for b, bpm, t in grid)) == data
        if path.suffix == ".DAT":
            assert edit.ticks(result) == tuple(((b - first) % 4 + 1, bpm, t) for b, bpm, t in grid)
        if path.suffix == ".2EX":
            assert result == data


def test_save_backs_up_exact_originals_and_preserves_all_other_data(library, tmp_path):
    db, content, files, grid = library
    plan = edit.make_plan(snap(library), 2)
    assert all(p.read_bytes() == raw for p, raw in files.items())  # preview never writes
    result = edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")
    assert result["ok"] and result["changed_files"] == 2
    manifest = json.loads((tmp_path / "backups" / plan["plan_id"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "saved"
    for entry in manifest["files"]:
        original = next(p for p in files if str(p) == entry["original"])
        assert (tmp_path / "backups" / plan["plan_id"] / entry["backup"]).read_bytes() == files[original]
    for path, raw in files.items():
        assert path.read_bytes() == edit.patch_grid(raw, 2, grid)
    with pytest.raises(edit.GridEditError, match="有効期限"):
        edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")


def test_running_rekordbox_blocks_save_but_allows_preview(library, tmp_path, monkeypatch):
    db, content, files, _ = library
    monkeypatch.setattr(edit, "save_block_reason", lambda: "rekordbox を終了してください")
    plan = edit.make_plan(snap(library), 3)
    assert plan["blocked_reason"]
    with pytest.raises(edit.GridEditError, match="終了"):
        edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")
    assert not (tmp_path / "backups").exists()
    assert all(p.read_bytes() == raw for p, raw in files.items())


@pytest.mark.parametrize("extension", [".DAT", ".EXT", ".2EX"])
def test_any_companion_change_invalidates_plan(library, tmp_path, extension):
    db, content, files, _ = library
    plan = edit.make_plan(snap(library), 4)
    changed = next(p for p in files if p.suffix == extension)
    # A header byte unrelated to grid may have been changed by rekordbox.
    raw = bytearray(files[changed]); raw[15] ^= 1
    changed.write_bytes(raw)
    with pytest.raises(edit.GridEditError, match="変わりました"):
        edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")
    assert changed.read_bytes() == raw
    assert all(p.read_bytes() == original for p, original in files.items() if p != changed)


def test_partial_save_failure_restores_already_written_file(library, tmp_path, monkeypatch):
    db, content, files, _ = library
    plan = edit.make_plan(snap(library), 2)
    replace = edit.os.replace
    calls = []
    def fail_second(source, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("simulated sharing violation")
        return replace(source, target)
    monkeypatch.setattr(edit.os, "replace", fail_second)
    with pytest.raises(edit.GridEditError, match="元に戻しました"):
        edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")
    assert all(p.read_bytes() == raw for p, raw in files.items())
    assert not list(tmp_path.glob(".aicue-grid-*.tmp"))
    manifest = json.loads((tmp_path / "backups" / plan["plan_id"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rolled_back"


def test_failed_rollback_reports_backup_and_preserves_recovery_manifest(library, tmp_path, monkeypatch):
    db, content, _, _ = library
    plan = edit.make_plan(snap(library), 2)
    replace = edit.os.replace
    count = 0
    def fail_after_first(source, target):
        nonlocal count
        count += 1
        if count > 1:
            raise OSError("simulated device failure")
        return replace(source, target)
    monkeypatch.setattr(edit.os, "replace", fail_after_first)
    with pytest.raises(edit.GridEditError, match="復元が必要") as exc:
        edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")
    assert plan["plan_id"] in str(exc.value)
    manifest = json.loads((tmp_path / "backups" / plan["plan_id"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "restore_required" and manifest["restore_required"]


def test_recovery_instructions_survive_manifest_update_failure(library, tmp_path, monkeypatch):
    db, content, _, _ = library
    plan = edit.make_plan(snap(library), 2)
    replace = edit.os.replace
    write_manifest = edit._write_manifest
    count = 0
    def fail_after_first(source, target):
        nonlocal count
        count += 1
        if count > 1:
            raise OSError("device failure")
        return replace(source, target)
    def fail_recovery_record(path, manifest):
        if manifest["status"] == "restore_required":
            raise OSError("disk full")
        return write_manifest(path, manifest)
    monkeypatch.setattr(edit.os, "replace", fail_after_first)
    monkeypatch.setattr(edit, "_write_manifest", fail_recovery_record)
    with pytest.raises(edit.GridEditError, match="復元が必要") as exc:
        edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")
    assert str(tmp_path / "backups" / plan["plan_id"]) in str(exc.value)


def test_rejects_mismatched_extended_anchors_before_any_write(library):
    _, _, files, _ = library
    ext = next(p for p in files if p.suffix == ".EXT")
    data = bytearray(ext.read_bytes())
    pos = next(pos for kind, pos, _, _ in edit.sections(data) if kind == b"PQT2")
    struct.pack_into(">I", data, pos + 28, 99999)
    ext.write_bytes(data)
    with pytest.raises(edit.GridEditError, match="先頭・末尾"):
        snap(library)


def test_plan_cannot_be_used_for_other_track_and_expires(library, tmp_path, monkeypatch):
    db, content, files, _ = library
    plan = edit.make_plan(snap(library), 2)
    with pytest.raises(edit.GridEditError):
        edit.apply_plan(db, "another-track", plan["plan_id"], tmp_path / "backups")
    now = edit.time.time()
    monkeypatch.setattr(edit.time, "time", lambda: now + 601)
    with pytest.raises(edit.GridEditError):
        edit.apply_plan(db, content.ID, plan["plan_id"], tmp_path / "backups")
    assert all(p.read_bytes() == raw for p, raw in files.items())


def test_api_requires_auth_and_explicit_confirmed_plan(library, tmp_path, monkeypatch):
    _, content, files, _ = library
    from app.config import get_settings
    (tmp_path / "app-data").mkdir()
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "app-data")
    headers = {"Authorization": f"Bearer {app.state.token}"}
    base = f"/api/v1/rekordbox/tracks/{content.ID}/grid"
    with TestClient(app) as client:
        assert client.get(base, params={"path": content.FolderPath}).status_code == 401
        assert client.post(base + "/apply", json={"plan_id": "0" * 32}).status_code == 401
        assert client.post(base + "/plan", headers=headers, json={"path": content.FolderPath, "first_beat": 1}).status_code == 422
        preview = client.get(base, params={"path": content.FolderPath}, headers=headers)
        assert preview.status_code == 200 and preview.json()["beats"][0]["before"] == 3
        assert client.get(base, params={"path": "wrong.wav"}, headers=headers).status_code == 409
        plan = client.post(base + "/plan", headers=headers, json={"path": content.FolderPath, "first_beat": 3}).json()
        assert plan["beats"][0]["after"] == 1
        assert all(p.read_bytes() == raw for p, raw in files.items())
        result = client.post(base + "/apply", headers=headers, json={"plan_id": plan["plan_id"]})
        assert result.status_code == 200 and result.json()["ok"]


def test_process_check_fails_closed_when_inspection_fails(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "process_iter", lambda *args: iter([SimpleNamespace(info={"name": None})]))
    assert edit.save_block_reason() is not None
    monkeypatch.setattr(psutil, "process_iter", lambda *args: iter([SimpleNamespace(info={"name": "rekordbox.exe"})]))
    assert "終了" in edit.save_block_reason()
    def unavailable(*args):
        raise psutil.AccessDenied(42)
    monkeypatch.setattr(psutil, "process_iter", unavailable)
    assert "確認できません" in edit.save_block_reason()


@pytest.mark.parametrize("data", [b"", b"PMAI" + bytes(24), anlz(tag(b"NOPE", 12))[:-1]])
def test_rejects_malformed_analysis(data):
    with pytest.raises(edit.GridEditError):
        list(edit.sections(data))
