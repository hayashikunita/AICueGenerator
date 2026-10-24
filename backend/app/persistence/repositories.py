"""永続化リポジトリ（基本設計書 §4）。

パラメータ化 SQL のみ使用（SQL インジェクション対策）。各書込メソッドは即コミットする
（ローカル単一利用者・WAL 前提）。時刻は UTC ISO8601、ID は 32桁16進。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..common import dumps, loads, new_id, utcnow_iso
from .db import connect


class Repository:
    """アプリ SQLite への CRUD ファサード。スレッドごとに 1 インスタンス。"""

    def __init__(self, db_path: Path) -> None:
        self._conn = connect(db_path)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- track_ref ---------------------------------------------------------
    def upsert_track(
        self,
        *,
        content_id: str,
        path: str,
        fmt: str,
        duration_ms: int | None = None,
        sample_rate: int | None = None,
        rb_uuid: str | None = None,
        writable: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        row = self._conn.execute(
            "SELECT id FROM track_ref WHERE content_id = ?", (content_id,)
        ).fetchone()
        if row:
            self._conn.execute(
                "UPDATE track_ref SET path=?, format=?, duration_ms=?, sample_rate=?, "
                "rb_uuid=?, writable=?, metadata_json=? WHERE content_id=?",
                (
                    path,
                    fmt,
                    duration_ms,
                    sample_rate,
                    rb_uuid,
                    int(writable),
                    dumps(metadata) if metadata else None,
                    content_id,
                ),
            )
            self._conn.commit()
            return str(row["id"])
        tid = new_id()
        self._conn.execute(
            "INSERT INTO track_ref (id, content_id, rb_uuid, path, format, duration_ms, "
            "sample_rate, metadata_json, writable, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                content_id,
                rb_uuid,
                path,
                fmt,
                duration_ms,
                sample_rate,
                dumps(metadata) if metadata else None,
                int(writable),
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return tid

    def get_track(self, track_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM track_ref WHERE id = ?", (track_id,)
        ).fetchone()

    # --- analysis_job ------------------------------------------------------
    def create_job(self, *, params: dict[str, Any], track_ids: list[str]) -> str:
        now = utcnow_iso()
        job_id = new_id()
        self._conn.execute(
            "INSERT INTO analysis_job (id, status, params_json, total, completed, failed, "
            "created_at, updated_at) VALUES (?,?,?,?,0,0,?,?)",
            (job_id, "PENDING", dumps(params), len(track_ids), now, now),
        )
        self._conn.executemany(
            "INSERT INTO job_track (job_id, track_id, status) VALUES (?,?,?)",
            [(job_id, tid, "PENDING") for tid in track_ids],
        )
        self._conn.commit()
        return job_id

    def set_job_status(self, job_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE analysis_job SET status=?, updated_at=? WHERE id=?",
            (status, utcnow_iso(), job_id),
        )
        self._conn.commit()

    def bump_job_counts(self, job_id: str, *, completed: int = 0, failed: int = 0) -> None:
        self._conn.execute(
            "UPDATE analysis_job SET completed=completed+?, failed=failed+?, updated_at=? "
            "WHERE id=?",
            (completed, failed, utcnow_iso(), job_id),
        )
        self._conn.commit()

    def set_job_track_status(
        self, job_id: str, track_id: str, status: str, error_id: str | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE job_track SET status=?, error_id=? WHERE job_id=? AND track_id=?",
            (status, error_id, job_id, track_id),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT j.*, (SELECT t.path FROM job_track jt JOIN track_ref t ON t.id=jt.track_id "
            "WHERE jt.job_id=j.id ORDER BY t.path LIMIT 1) AS track_path "
            "FROM analysis_job j WHERE j.id = ?", (job_id,)
        ).fetchone()

    def list_jobs(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT j.*, (SELECT t.path FROM job_track jt JOIN track_ref t ON t.id=jt.track_id "
            "WHERE jt.job_id=j.id ORDER BY t.path LIMIT 1) AS track_path "
            "FROM analysis_job j ORDER BY j.created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def list_job_tracks(self, job_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM job_track WHERE job_id = ?", (job_id,)
        ).fetchall()

    def set_job_track_analysis(self, job_id: str, track_id: str, analysis: dict[str, Any], run_id: str | None = None) -> None:
        self._conn.execute(
            "UPDATE job_track SET analysis_json=?, run_id=? WHERE job_id=? AND track_id=?",
            (dumps(analysis), run_id, job_id, track_id),
        )
        self._conn.commit()

    # --- analysis_run ------------------------------------------------------
    def find_cached_run(
        self, *, track_id: str, engine_version: str, fingerprint: str, params: dict[str, Any]
    ) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM analysis_run WHERE track_id=? AND engine_version=? AND "
            "audio_fingerprint=? AND params_json=? AND status='COMPLETED'",
            (track_id, engine_version, fingerprint, dumps(params)),
        ).fetchone()

    def create_run(
        self,
        *,
        track_id: str,
        engine_version: str,
        params: dict[str, Any],
        fingerprint: str,
        beat_source: str,
        pssi_used: bool,
    ) -> str:
        run_id = new_id()
        self._conn.execute(
            "INSERT INTO analysis_run (id, track_id, engine_version, params_json, "
            "audio_fingerprint, beat_source, pssi_used, status, started_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                track_id,
                engine_version,
                dumps(params),
                fingerprint,
                beat_source,
                int(pssi_used),
                "RUNNING",
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return run_id

    def finish_run(self, run_id: str, *, status: str, error_id: str | None = None) -> None:
        self._conn.execute(
            "UPDATE analysis_run SET status=?, error_id=?, finished_at=? WHERE id=?",
            (status, error_id, utcnow_iso(), run_id),
        )
        self._conn.commit()

    def save_feature_summary(
        self,
        run_id: str,
        *,
        bpm: float | None,
        beat_times: list[float],
        downbeats: list[int],
        energy: list[float] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO feature_summary (run_id, bpm, beat_times_json, "
            "downbeats_json, energy_json) VALUES (?,?,?,?,?)",
            (run_id, bpm, dumps(beat_times), dumps(downbeats), dumps(energy) if energy else None),
        )
        self._conn.commit()

    # --- cue_candidate -----------------------------------------------------
    def get_feature_summary(self, run_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM feature_summary WHERE run_id=?", (run_id,)).fetchone()

    def add_manual_candidate(self, job_id: str, track_id: str, candidate: dict[str, Any]) -> str:
        """Fork a completed job's run so manual additions never alter older history."""
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            job = self.get_job(job_id)
            if job is None or job["status"] != "COMPLETED":
                raise ValueError("解析完了後に候補を追加してください。")
            jt = next((r for r in self.list_job_tracks(job_id) if r["track_id"] == track_id), None)
            if jt is None or not jt["run_id"]:
                raise ValueError("解析済みの対象曲が見つかりません。")
            old_run = self._conn.execute("SELECT * FROM analysis_run WHERE id=?", (jt["run_id"],)).fetchone()
            if old_run is None:
                raise ValueError("解析結果が見つかりません。")
            run_id, candidate_id, now = new_id(), new_id(), utcnow_iso()
            params = loads(old_run["params_json"]) or {}
            params["manual_revision"] = new_id()
            self._conn.execute("INSERT INTO analysis_run (id,track_id,engine_version,params_json,audio_fingerprint,beat_source,pssi_used,status,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (run_id, track_id, old_run["engine_version"], dumps(params), old_run["audio_fingerprint"], old_run["beat_source"], old_run["pssi_used"], "COMPLETED", now, now))
            self._conn.execute("INSERT INTO feature_summary SELECT ?,bpm,beat_times_json,downbeats_json,bars_json,energy_json,waveform_peaks_json FROM feature_summary WHERE run_id=?", (run_id, old_run["id"]))
            for original in self._conn.execute("SELECT * FROM cue_candidate WHERE run_id=?", (old_run["id"],)).fetchall():
                copied_id = new_id()
                self._conn.execute("INSERT INTO cue_candidate SELECT ?,?,type,time_ms,beat,bar,confidence,rank,evidence_json,? FROM cue_candidate WHERE id=?", (copied_id, run_id, now, original["id"]))
                self._conn.execute("INSERT INTO cue_decision SELECT ?,?,accepted,edited_time_ms,cue_kind,slot,color,comment,updated_at FROM cue_decision WHERE candidate_id=?", (new_id(), copied_id, original["id"]))
            rank = self._conn.execute("SELECT COALESCE(MAX(rank),0)+1 FROM cue_candidate WHERE run_id=? AND type=?", (run_id, candidate["type"])).fetchone()[0]
            self._conn.execute("INSERT INTO cue_candidate (id,run_id,type,time_ms,beat,bar,confidence,rank,evidence_json,created_at) VALUES (?,?,?,?,?,NULL,0,?,?,?)", (candidate_id, run_id, candidate["type"], candidate["time_ms"], candidate["beat"], rank, dumps(candidate["evidence"]), now))
            self._conn.execute("UPDATE job_track SET run_id=? WHERE job_id=? AND track_id=?", (run_id, job_id, track_id))
        return candidate_id

    def add_candidates(self, run_id: str, candidates: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        now = utcnow_iso()
        rows = []
        for c in candidates:
            cid = new_id()
            ids.append(cid)
            rows.append(
                (
                    cid,
                    run_id,
                    c["type"],
                    int(c["time_ms"]),
                    c.get("beat"),
                    c.get("bar"),
                    int(round(c["confidence"])),
                    int(c["rank"]),
                    dumps(c.get("evidence", [])),
                    now,
                )
            )
        self._conn.executemany(
            "INSERT INTO cue_candidate (id, run_id, type, time_ms, beat, bar, confidence, "
            "rank, evidence_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self._conn.commit()
        return ids

    def get_candidate(self, candidate_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT c.*, d.accepted, d.cue_kind,d.edited_time_ms,d.slot,d.color,d.comment,fs.beat_times_json FROM cue_candidate c "
            "LEFT JOIN cue_decision d ON d.candidate_id=c.id LEFT JOIN feature_summary fs ON fs.run_id=c.run_id WHERE c.id = ?", (candidate_id,)
        ).fetchone()

    def list_candidates_for_job(self, job_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT c.*, d.accepted, d.cue_kind,d.edited_time_ms,fs.beat_times_json FROM cue_candidate c "
            "LEFT JOIN cue_decision d ON d.candidate_id=c.id "
            "JOIN analysis_run r ON c.run_id = r.id "
            "LEFT JOIN feature_summary fs ON fs.run_id=r.id "
            "JOIN job_track jt ON jt.track_id = r.track_id "
            "JOIN analysis_job j ON jt.job_id = j.id "
            "WHERE jt.job_id = ? AND (jt.run_id = r.id OR "
            "(jt.run_id IS NULL AND jt.analysis_json IS NULL AND r.params_json = j.params_json)) ORDER BY c.type, c.rank",
            (job_id,),
        ).fetchall()

    def list_candidates_for_run(self, run_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM cue_candidate WHERE run_id = ? ORDER BY type, rank", (run_id,)
        ).fetchall()

    # --- cue_decision ------------------------------------------------------
    def upsert_decision(
        self,
        *,
        candidate_id: str,
        accepted: bool,
        cue_kind: str,
        edited_time_ms: int | None = None,
        slot: str | None = None,
        color: str | None = None,
        comment: str | None = None,
    ) -> str:
        existing = self._conn.execute(
            "SELECT id FROM cue_decision WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        now = utcnow_iso()
        if existing:
            self._conn.execute(
                "UPDATE cue_decision SET accepted=?, edited_time_ms=?, cue_kind=?, slot=?, "
                "color=?, comment=?, updated_at=? WHERE candidate_id=?",
                (int(accepted), edited_time_ms, cue_kind, slot, color, comment, now, candidate_id),
            )
            self._conn.commit()
            return str(existing["id"])
        did = new_id()
        self._conn.execute(
            "INSERT INTO cue_decision (id, candidate_id, accepted, edited_time_ms, cue_kind, "
            "slot, color, comment, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (did, candidate_id, int(accepted), edited_time_ms, cue_kind, slot, color, comment, now),
        )
        self._conn.commit()
        return did

    def list_accepted_decisions_for_job(self, job_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT d.*, c.type AS cue_type, c.time_ms AS orig_time_ms, r.track_id AS track_id "
            "FROM cue_decision d "
            "JOIN cue_candidate c ON d.candidate_id = c.id "
            "JOIN analysis_run r ON c.run_id = r.id "
            "JOIN job_track jt ON jt.track_id = r.track_id "
            "JOIN analysis_job j ON jt.job_id = j.id "
            "WHERE jt.job_id = ? AND (jt.run_id = r.id OR "
            "(jt.run_id IS NULL AND jt.analysis_json IS NULL AND r.params_json = j.params_json)) AND d.accepted = 1",
            (job_id,),
        ).fetchall()

    # --- write_plan / backup / audit --------------------------------------
    def create_write_plan(
        self, *, job_id: str | None, confirmation_hash: str, backup_id: str | None = None
    ) -> str:
        pid = new_id()
        self._conn.execute(
            "INSERT INTO write_plan (id, job_id, confirmation_hash, status, backup_id, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (pid, job_id, confirmation_hash, "DRAFT", backup_id, utcnow_iso()),
        )
        self._conn.commit()
        return pid

    def add_write_plan_items(self, plan_id: str, items: list[dict[str, Any]]) -> None:
        rows = [
            (
                new_id(),
                plan_id,
                it["track_id"],
                it["action"],
                it["cue_kind"],
                it.get("slot"),
                dumps(it.get("before")) if it.get("before") is not None else None,
                dumps(it.get("after")) if it.get("after") is not None else None,
                it.get("reason"),
            )
            for it in items
        ]
        self._conn.executemany(
            "INSERT INTO write_plan_item (id, plan_id, track_id, action, cue_kind, slot, "
            "before_json, after_json, reason) VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self._conn.commit()

    def get_write_plan(self, plan_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM write_plan WHERE id = ?", (plan_id,)
        ).fetchone()

    def list_write_plan_items(self, plan_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM write_plan_item WHERE plan_id = ?", (plan_id,)
        ).fetchall()

    def set_write_plan_status(self, plan_id: str, status: str, *, executed: bool = False) -> None:
        if executed:
            self._conn.execute(
                "UPDATE write_plan SET status=?, executed_at=? WHERE id=?",
                (status, utcnow_iso(), plan_id),
            )
        else:
            self._conn.execute(
                "UPDATE write_plan SET status=? WHERE id=?", (status, plan_id)
            )
        self._conn.commit()

    def add_backup(
        self, *, path: str, size_bytes: int, sha: str, db_version: str | None = None
    ) -> str:
        bid = new_id()
        self._conn.execute(
            "INSERT INTO backup_record (id, path, created_at, size_bytes, hash, db_version) "
            "VALUES (?,?,?,?,?,?)",
            (bid, path, utcnow_iso(), size_bytes, sha, db_version),
        )
        self._conn.commit()
        return bid

    def add_audit(
        self,
        *,
        actor: str,
        action: str,
        result: str,
        target: str | None = None,
        before: Any = None,
        after: Any = None,
        error_id: str | None = None,
        job_id: str | None = None,
        track_id: str | None = None,
    ) -> str:
        aid = new_id()
        self._conn.execute(
            "INSERT INTO audit_event (id, actor, action, target, before_json, after_json, "
            "result, error_id, job_id, track_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                aid,
                actor,
                action,
                target,
                dumps(before) if before is not None else None,
                dumps(after) if after is not None else None,
                result,
                error_id,
                job_id,
                track_id,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return aid

    def list_audit(self, limit: int = 200) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM audit_event ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


__all__ = ["Repository", "row_to_dict", "loads"]
