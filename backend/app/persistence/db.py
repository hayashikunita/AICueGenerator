from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    """WAL・外部キー有効化済みの SQLite 接続を返す。"""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path) -> None:
    """スキーマを適用する。適用済みなら冪等に何もしない。"""
    schema_sql = (_MIGRATIONS_DIR / "0001_initial.sql").read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        conn.executescript(schema_sql)
        row = conn.execute(
            "SELECT 1 FROM schema_version WHERE version = ?", (SCHEMA_VERSION,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()
    finally:
        conn.close()
