from __future__ import annotations

from app.domain.enums import ErrorCode
from app.rekordbox.backup import create_backup, restore_backup, verify_backup
from app.rekordbox.errors import AdapterError


def _make_db(path):
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 4096)
    return path


def test_create_and_verify_backup(tmp_path):
    src = _make_db(tmp_path / "master.db")
    info = create_backup(src, tmp_path / "backups")
    assert info.path.exists()
    assert verify_backup(info)


def test_restore_refused_when_rekordbox_running(tmp_path):
    src = _make_db(tmp_path / "master.db")
    info = create_backup(src, tmp_path / "backups")
    dest = tmp_path / "restored.db"
    try:
        restore_backup(info.path, dest, rekordbox_running=True)
        assert False, "should have raised"
    except AdapterError as e:
        assert e.code is ErrorCode.RBX_RUNNING


def test_restore_ok_when_not_running(tmp_path):
    src = _make_db(tmp_path / "master.db")
    info = create_backup(src, tmp_path / "backups")
    dest = tmp_path / "restored.db"
    restore_backup(info.path, dest, rekordbox_running=False)
    assert dest.exists()
    assert dest.read_bytes() == src.read_bytes()
