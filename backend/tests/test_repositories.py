from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.persistence.repositories import Repository


def _repo() -> Repository:
    return Repository(get_settings().db_path)


def test_track_upsert_is_idempotent_by_content_id():
    with _repo() as repo:
        t1 = repo.upsert_track(content_id="C1", path="a.wav", fmt="WAV")
        t2 = repo.upsert_track(content_id="C1", path="b.wav", fmt="WAV")
        assert t1 == t2
        row = repo.get_track(t1)
        assert row["path"] == "b.wav"


def test_job_create_and_status_flow():
    with _repo() as repo:
        tid = repo.upsert_track(content_id="C2", path="a.wav", fmt="WAV")
        job_id = repo.create_job(params={"bpm": 128}, track_ids=[tid])
        job = repo.get_job(job_id)
        assert job["status"] == "PENDING"
        assert job["total"] == 1
        repo.set_job_status(job_id, "RUNNING")
        repo.bump_job_counts(job_id, completed=1)
        job = repo.get_job(job_id)
        assert job["status"] == "RUNNING"
        assert job["completed"] == 1


def test_candidates_and_decision_roundtrip():
    with _repo() as repo:
        tid = repo.upsert_track(content_id="C3", path="a.wav", fmt="WAV")
        run_id = repo.create_run(
            track_id=tid,
            engine_version="0.1.0",
            params={},
            fingerprint="fp",
            beat_source="ANLZ",
            pssi_used=False,
        )
        ids = repo.add_candidates(
            run_id,
            [
                {"type": "DROP", "time_ms": 60000, "beat": 128, "confidence": 87, "rank": 1,
                 "evidence": [{"name": "x", "weight": 25, "score": 1.0, "detail": ""}]},
            ],
        )
        assert len(ids) == 1
        cand = repo.get_candidate(ids[0])
        assert cand["type"] == "DROP"
        did = repo.upsert_decision(candidate_id=ids[0], accepted=True, cue_kind="MEMORY")
        assert did
        # idempotent update returns same decision row
        did2 = repo.upsert_decision(candidate_id=ids[0], accepted=True, cue_kind="HOT")
        assert did == did2


def test_cached_run_lookup():
    with _repo() as repo:
        tid = repo.upsert_track(content_id="C4", path="a.wav", fmt="WAV")
        params = {"bpm": 128, "top_k": 3}
        repo.create_run(
            track_id=tid, engine_version="0.1.0", params=params,
            fingerprint="fp4", beat_source="ANLZ", pssi_used=False,
        )
        # RUNNING は未完了なのでキャッシュ対象外
        assert repo.find_cached_run(
            track_id=tid, engine_version="0.1.0", fingerprint="fp4", params=params
        ) is None
