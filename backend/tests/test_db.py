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
    init_db(db_path)  # 2回目でマイグレーションを重複実行しない。
    conn = connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM schema_version").fetchone()["c"]
        assert count == SCHEMA_VERSION
    finally:
        conn.close()


def test_upgrade_preserves_existing_history_and_decisions(tmp_path):
    from app.persistence.repositories import Repository

    db_path = tmp_path / "legacy.db"
    schema_path = Path(__file__).parent.parent / "app/persistence/migrations/0001_initial.sql"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_version VALUES (1, 'legacy')")
    with Repository(db_path) as repo:
        track_id = repo.upsert_track(content_id="legacy", path="existing.wav", fmt="WAV")
        job_id = repo.create_job(params={}, track_ids=[track_id])
        run_id = repo.create_run(track_id=track_id, engine_version="old", params={}, fingerprint="old", beat_source="ANLZ", pssi_used=False)
        ids = repo.add_candidates(run_id, [{"type": "DROP", "time_ms": 1000, "confidence": 90, "rank": 1}])
        repo.upsert_decision(candidate_id=ids[0], accepted=True, cue_kind="MEMORY")
    init_db(db_path)
    init_db(db_path)
    with Repository(db_path) as repo:
        assert repo.get_track(track_id)["path"] == "existing.wav"
        assert repo.list_candidates_for_job(job_id)[0]["id"] == ids[0]
        assert len(repo.list_accepted_decisions_for_job(job_id)) == 1
        assert repo.list_job_tracks(job_id)[0]["analysis_json"] is None
