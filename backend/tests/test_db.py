from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from app.persistence.db import SCHEMA_VERSION, connect, init_db

EXPECTED_TABLES = {
    "schema_version",
    "track_ref",
    "analysis_job",
    "job_track",
    "analysis_run",
    "feature_summary",
    "cue_candidate",
    "cue_decision",
    "backup_record",
    "write_plan",
    "write_plan_item",
    "audit_event",
}


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_init_db_creates_all_tables() -> None:
    db_path = Path(tempfile.mkdtemp(prefix="aicue-dbtest-")) / "app.db"
    init_db(db_path)
    conn = connect(db_path)
    try:
        assert EXPECTED_TABLES.issubset(_tables(conn))
        version = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
        assert version == SCHEMA_VERSION
    finally:
        conn.close()


def test_init_db_is_idempotent() -> None:
    db_path = Path(tempfile.mkdtemp(prefix="aicue-dbtest-")) / "app.db"
    init_db(db_path)
    init_db(db_path)  # 2回目でも例外なく、schema_version は1行のまま。
    conn = connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM schema_version").fetchone()["c"]
        assert count == 1
    finally:
        conn.close()
