import pytest

from app.analysis.intro_ordinal_repair import repair_intro_ordinals
from app.common import loads
from app.persistence.db import init_db
from app.persistence.repositories import Repository
from app.schemas.jobs import JobParams


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED"])
def test_saved_grid_repairs_missing_positions_preserves_decisions_and_other_jobs(tmp_path, monkeypatch, status):
    from app.analysis import ai, pipeline
    monkeypatch.setattr(ai, "analyze_stems", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No AI needed")))
    monkeypatch.setattr(pipeline, "analyze_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No audio analysis needed")))
    db = tmp_path / "repair.db"
    init_db(db)
    params = JobParams(cue_mode="INTRO_OUTRO", intro_outro={"targets": ["INTRO_START", "INTRO_END", "INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3"]}).model_dump()
    with Repository(db) as repo:
        track = repo.upsert_track(content_id="test", path=str(tmp_path / "missing.wav"), fmt="WAV")
        job = repo.create_job(params=params, track_ids=[track])
        run, _ = repo.save_completed_run(job_id=job, track_id=track, engine_version="0.8.1", params=params,
            fingerprint="original", beat_source="ANLZ", pssi_used=True, bpm=120,
            beat_times=[.137 + index * .5 for index in range(100)], downbeats=list(range(2, 100, 4)),
            candidates=[{"type": "INTRO_START", "time_ms": 1137, "beat": 2, "confidence": 85, "rank": 1},
                        {"type": "INTRO_END", "time_ms": 5137, "beat": 10, "confidence": 85, "rank": 1}],
            analysis={"available": True, "duration_ms": 50000, "warnings": ["イントロの8小節目：古い範囲制限。", "別の注意事項"]})
        repo.set_job_status(job, status)
        end = next(row for row in repo.list_candidates_for_job(job) if row["type"] == "INTRO_END")
        repo.upsert_decision(candidate_id=end["id"], accepted=True, cue_kind="BOTH", edited_time_ms=5500,
                             slot="A", color="#9900ff", comment="Keep this")
        other = repo.create_job(params=params, track_ids=[track])
        repo.reuse_completed_run(job_id=other, track_id=track, run_id=run, params=params,
                                 analysis={"available": True, "duration_ms": 50000})
        repo.set_job_status(other, "COMPLETED")
        original_rows = [dict(row) for row in repo.list_candidates_for_job(other)]
        assert repair_intro_ordinals(repo, job) == {"tracks": 1, "added": 3, "missing_origin": 0}
        repaired = repo.list_candidates_for_job(job)
        assert {row["type"]: row["beat"] for row in repaired if row["type"].startswith("INTRO_BAR")} == {"INTRO_BAR": 30, "INTRO_BAR_X2": 62, "INTRO_BAR_X3": 94}
        for row in repaired:
            if row["type"].startswith("INTRO_BAR"):
                assert row["accepted"] is None
        copied_end = repo.get_candidate(next(row["id"] for row in repaired if row["type"] == "INTRO_END"))
        assert (copied_end["accepted"], copied_end["cue_kind"], copied_end["edited_time_ms"], copied_end["slot"], copied_end["color"], copied_end["comment"]) == (1, "BOTH", 5500, "A", "#9900ff", "Keep this")
        assert [dict(row) for row in repo.list_candidates_for_job(other)] == original_rows
        assert repo.get_job(job)["completed"] == repo.get_job(other)["completed"] == 1
        assert repo.get_job(job)["status"] == status
        analysis = loads(repo.list_job_tracks(job)[0]["analysis_json"])
        assert analysis["warnings"] == ["別の注意事項"]
        revised = repo.list_job_tracks(job)[0]["run_id"]
        assert repair_intro_ordinals(repo, job) == {"tracks": 0, "added": 0, "missing_origin": 0}
        assert repo.list_job_tracks(job)[0]["run_id"] == revised
