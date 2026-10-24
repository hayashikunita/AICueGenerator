import sqlite3
import time
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.common import new_id
from app.config import get_settings
from app.main import app
from app.persistence.repositories import Repository


def auth():
    return {"Authorization": f"Bearer {app.state.token}"}


@pytest.fixture
def batch_job(tmp_path):
    originals = []
    with TestClient(app) as client, Repository(get_settings().db_path) as repo:
        track_ids, runs, candidate_ids = [], [], []
        for i in range(2):
            source = tmp_path / str(i) / "same.wav"
            source.parent.mkdir()
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(bytes([i, 0]) * 8000)
            originals.append((source, source.read_bytes()))
            tid = repo.upsert_track(content_id=new_id(), path=str(source), fmt="WAV")
            run = repo.create_run(track_id=tid, engine_version="batch-test", params={}, fingerprint=new_id(), beat_source="ANLZ", pssi_used=True)
            repo.save_feature_summary(run, bpm=120 + i * 10, beat_times=[j * .5 for j in range(32)], downbeats=list(range(0, 32, 4)))
            ids = repo.add_candidates(run, [{"type": "CHORUS_START" if j < 4 else "OUTRO", "time_ms": j * 500, "beat": j, "confidence": 85, "rank": j + 1} for j in range(9)])
            repo.finish_run(run, status="COMPLETED")
            track_ids.append(tid)
            runs.append(run)
            candidate_ids.append(ids)
        job = repo.create_job(params={}, track_ids=track_ids)
        repo.set_job_status(job, "COMPLETED")
        for tid, run in zip(track_ids, runs):
            repo.set_job_track_analysis(job, tid, {"available": True, "source": "REKORDBOX"}, run)
            repo.set_job_track_status(job, tid, "COMPLETED")
        yield client, repo, job, track_ids, candidate_ids
    assert all(path.read_bytes() == original for path, original in originals)


def accept(client, job, ids, kind="MEMORY", headers=None):
    return client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=auth() if headers is None else headers,
                       json={"candidate_ids": ids, "cue_kind": kind})


def test_batch_association_and_atomic_accept_preserve_adjustments(batch_job):
    client, repo, job, tracks, ids = batch_job
    rows = client.get(f"/api/v1/jobs/{job}/candidates", headers=auth()).json()["candidates"]
    assert len(rows) == 18 and {c["track_id"] for c in rows} == set(tracks)
    assert client.get(f"/api/v1/candidates/{ids[1][0]}", headers=auth()).json()["track_id"] == tracks[1]
    repo.upsert_decision(candidate_id=ids[0][0], accepted=False, cue_kind="HOT", edited_time_ms=750, slot="H", color="#112233", comment="Keep")
    selected = ids[0][:2] + ids[1][:2]
    response = accept(client, job, selected, "BOTH")
    assert response.status_code == 200, response.text
    assert {c["id"] for c in response.json()["candidates"] if c["accepted"]} == set(selected)
    assert all(c["cue_kind"] == "BOTH" for c in response.json()["candidates"] if c["accepted"])
    row = repo.get_candidate(ids[0][0])
    assert (row["edited_time_ms"], row["slot"], row["color"], row["comment"]) == (750, "H", "#112233", "Keep")


def test_batch_validates_scope_duplicates_auth_and_job_state(batch_job):
    client, repo, job, tracks, ids = batch_job
    assert accept(client, job, ids[0][:1], headers={}).status_code == 401
    assert accept(client, job, [ids[0][0], "outside-job"]).status_code == 409
    assert accept(client, job, [ids[0][0], ids[0][0]]).status_code == 409
    assert accept(client, job, []).status_code == 422
    assert accept(client, "absent", ids[0][:1]).status_code == 404
    repo.set_job_status(job, "RUNNING")
    assert accept(client, job, ids[0][:1]).status_code == 409
    assert all(repo.get_candidate(cid)["accepted"] is None for group in ids for cid in group)


def test_hot_limit_is_per_track_including_existing_accepted(batch_job):
    client, repo, job, tracks, ids = batch_job
    assert accept(client, job, ids[0][:8] + ids[1][:8], "HOT").status_code == 200
    response = accept(client, job, [ids[0][8], ids[1][0]], "BOTH")
    assert response.status_code == 409 and "8件" in response.json()["detail"]
    assert repo.get_candidate(ids[0][8])["accepted"] is None
    assert repo.get_candidate(ids[1][0])["cue_kind"] == "HOT"
    assert accept(client, job, [ids[0][8]], "MEMORY").status_code == 200


def test_batch_database_failure_rolls_back_whole_selection(batch_job):
    _, repo, job, _, ids = batch_job
    with repo._conn:
        repo._conn.execute(f"CREATE TEMP TRIGGER fail_batch BEFORE INSERT ON cue_decision WHEN NEW.candidate_id='{ids[1][0]}' BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.accept_candidates(job, [ids[0][0], ids[1][0]], "MEMORY")
    assert repo.get_candidate(ids[0][0])["accepted"] is None


def test_multitrack_export_retains_same_named_audio_and_prior_exports(batch_job):
    client, repo, job, tracks, ids = batch_job
    assert accept(client, job, ids[0][:8] + ids[1][:8], "BOTH").status_code == 200
    response = client.post("/api/v1/write/export-xml", headers=auth(), json={"job_id": job})
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["tracks"], data["cues"], data["copied"]) == (2, 32, 2)
    folder = Path(data["folder"])
    copies = sorted(folder.glob("*.wav"))
    assert len(copies) == 2
    assert {p.read_bytes() for p in copies} == {Path(repo.get_track(t)["path"]).read_bytes() for t in tracks}
    tree = ET.parse(data["xml_path"])
    xml_tracks = tree.getroot().find("COLLECTION").findall("TRACK")
    assert len({t.get("Location") for t in xml_tracks}) == 2
    for track in xml_tracks:
        assert sorted(int(m.get("Num")) for m in track.findall("POSITION_MARK") if int(m.get("Num")) >= 0) == list(range(8))
    original_xml = Path(data["xml_path"]).read_bytes()
    again = client.post("/api/v1/write/export-xml", headers=auth(), json={"job_id": job}).json()
    assert again["folder"] != data["folder"]
    assert Path(data["xml_path"]).read_bytes() == original_xml
    report = client.get(f"/api/v1/jobs/{job}/export.csv", headers=auth()).text
    assert all(repo.get_track(t)["content_id"] in report for t in tracks)


def test_create_rejects_duplicate_tracks_before_job_creation(batch_job):
    client, repo, job, tracks, _ = batch_job
    row = repo.get_track(tracks[0])
    one = {"content_id": row["content_id"], "path": row["path"]}
    before = len(repo.list_jobs())
    assert client.post("/api/v1/jobs", headers=auth(), json={"tracks": [one, one]}).status_code == 422
    assert client.post("/api/v1/jobs", headers=auth(), json={"tracks": [one, {**one, "content_id": "other"}]}).status_code == 422
    assert len(repo.list_jobs()) == before


def test_real_worker_multitrack_targets_continues_after_missing_audio(batch_job):
    client, repo, _, tracks, _ = batch_job
    inputs = [{"content_id": repo.get_track(t)["content_id"], "path": repo.get_track(t)["path"]} for t in tracks]
    inputs.insert(1, {"content_id": new_id(), "path": str(Path(inputs[0]["path"]).parent / "absent.wav")})
    targets = ["INTRO_START", "OUTRO"]
    response = client.post("/api/v1/jobs", headers=auth(), json={"params": {"analysis_source": "AUDIO", "bpm": 120, "cue_targets": targets}, "tracks": inputs})
    assert response.status_code == 201, response.text
    job = response.json()["job_id"]
    for _ in range(300):
        summary = client.get(f"/api/v1/jobs/{job}", headers=auth()).json()
        if summary["status"] in {"COMPLETED", "FAILED"}:
            break
        time.sleep(.05)
    assert summary["status"] == "COMPLETED" and summary["total"] == 3
    assert (summary["completed"], summary["failed"]) == (2, 1)
    result = client.get(f"/api/v1/jobs/{job}/tracks", headers=auth()).json()["tracks"]
    assert sum(t["status"] == "COMPLETED" for t in result) == 2
    assert "音源が見つかりません" in next(t for t in result if t["status"] == "FAILED")["analysis"]["reason"]
    assert summary["params"]["cue_targets"] == targets
