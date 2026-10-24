import csv
import io
import wave
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.common import new_id
from app.config import get_settings
from app.main import app
from app.persistence.repositories import Repository


def auth():
    return {"Authorization": f"Bearer {app.state.token}"}


@pytest.fixture
def cue_history(tmp_path):
    source = tmp_path / "positions.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * 40)
    original = source.read_bytes()
    with TestClient(app) as client:
        with Repository(get_settings().db_path) as repo:
            track = repo.upsert_track(content_id=new_id(), path=str(source), fmt="WAV", duration_ms=40000)
            fingerprint = new_id()
            run = repo.create_run(track_id=track, engine_version="position-test", params={}, fingerprint=fingerprint, beat_source="ANLZ", pssi_used=True)
            times = [.137 + i * .5 + i // 16 * .03 for i in range(64)]
            repo.save_feature_summary(run, bpm=120, beat_times=times, downbeats=list(range(2, 64, 4)))
            ids = repo.add_candidates(run, [{"type": "INTRO_START", "time_ms": 137, "beat": 0, "confidence": 85, "rank": 1},
                                           {"type": "CHORUS_START", "time_ms": 8137, "beat": 16, "confidence": 85, "rank": 1}])
            repo.finish_run(run, status="COMPLETED")
            jobs = []
            for _ in range(2):
                job = repo.create_job(params={}, track_ids=[track])
                repo.set_job_status(job, "COMPLETED")
                repo.set_job_track_analysis(job, track, {"available": True, "source": "REKORDBOX"}, run)
                jobs.append(job)
        yield client, jobs, track, run, ids, times, fingerprint
    assert source.read_bytes() == original


def candidates(client, job):
    return client.get(f"/api/v1/jobs/{job}/candidates", headers=auth()).json()["candidates"]


def test_position_preview_is_read_only_and_uses_actual_beats_and_bars(cue_history):
    client, jobs, _, _, ids, times, _ = cue_history
    base = f"/api/v1/candidates/{ids[0]}/preview-position"
    assert client.post(base, json={"time_ms": 1234}).status_code == 401
    result = client.post(base, headers=auth(), json={"time_ms": 1234, "snap_to": "BEAT"}).json()
    assert result == {"time_ms": 1137, "beat": 2}
    bar = client.post(base, headers=auth(), json={"time_ms": 0, "snap_to": "BAR", "step": 1}).json()
    assert bar["beat"] == 6 and bar["time_ms"] == round(times[6] * 1000)
    assert all(c["accepted"] is None and c["edited_time_ms"] is None for c in candidates(client, jobs[0]))
    assert all(c["time_ms"] == c["original_time_ms"] for c in candidates(client, jobs[0]))


@pytest.mark.parametrize(("body", "status"), [
    ({"time_ms": -1}, 422), ({"time_ms": 999999}, 400),
    ({"time_ms": 0, "step": -1}, 400), ({"time_ms": 0, "snap_to": "SECONDS"}, 422),
])
def test_outside_grid_or_invalid_adjustments_do_not_mutate(cue_history, body, status):
    client, jobs, _, _, ids, _, _ = cue_history
    before = candidates(client, jobs[0])
    response = client.post(f"/api/v1/candidates/{ids[0]}/preview-position", headers=auth(), json=body)
    assert response.status_code == status
    assert candidates(client, jobs[0]) == before


def test_adjusted_position_survives_kind_changes_history_csv_and_xml(cue_history):
    client, jobs, _, _, ids, _, _ = cue_history
    url = f"/api/v1/candidates/{ids[0]}/decision"
    changed = client.post(url, headers=auth(), json={"accepted": True, "cue_kind": "BOTH", "edited_time_ms": 1137, "slot": "H"})
    assert changed.status_code == 200 and changed.json()["time_ms"] == 1137
    client.post(url, headers=auth(), json={"accepted": True, "cue_kind": "MEMORY"})
    client.post(url, headers=auth(), json={"accepted": True, "cue_kind": "BOTH"})
    row = client.get(f"/api/v1/candidates/{ids[0]}", headers=auth()).json()
    assert row["time_ms"] == 1137 and row["original_time_ms"] == 137 and row["beat"] == 2
    csv_text = client.get(f"/api/v1/jobs/{jobs[0]}/export.csv", headers=auth()).text
    assert next(r for r in csv.DictReader(io.StringIO(csv_text)) if r["type"] == "INTRO_START")["time_ms"] == "1137"
    exported = client.post("/api/v1/write/export-xml", headers=auth(), json={"job_id": jobs[0]})
    assert exported.status_code == 200
    marks = ET.parse(exported.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
    assert {m.get("Start") for m in marks} == {"1.137"}
    assert {m.get("Num") for m in marks} == {"-1", "7"}  # slot was preserved
    assert any(c["time_ms"] == 1137 for c in candidates(client, jobs[0]))
    bad = client.post(url, headers=auth(), json={"edited_time_ms": 999999})
    assert bad.status_code == 400


def test_manual_addition_forks_only_target_history_and_preserves_decisions(cue_history):
    client, jobs, track, run, ids, times, fingerprint = cue_history
    client.post(f"/api/v1/candidates/{ids[0]}/decision", headers=auth(), json={"accepted": True, "cue_kind": "MEMORY", "edited_time_ms": 1137, "comment": "Keep me"})
    previous = candidates(client, jobs[1])
    endpoint = f"/api/v1/jobs/{jobs[0]}/candidates/manual"
    assert client.post(endpoint, json={"track_id": track, "target": "VOCAL_START", "time_ms": 2000}).status_code == 401
    response = client.post(endpoint, headers=auth(), json={"track_id": track, "target": "VOCAL_START", "time_ms": 2100})
    assert response.status_code == 201, response.text
    manual = response.json()
    assert manual["accepted"] is None and manual["type"] == "VOCAL_START"
    assert "自動検出ではありません" in manual["evidence"][0]["detail"]
    assert candidates(client, jobs[1]) == previous
    current = candidates(client, jobs[0])
    assert len(current) == 3 and {c["id"] for c in current}.isdisjoint(ids)
    copied = next(c for c in current if c["type"] == "INTRO_START")
    assert copied["accepted"] and copied["time_ms"] == 1137 and copied["cue_kind"] == "MEMORY"
    with Repository(get_settings().db_path) as repo:
        cached = repo.find_cached_run(track_id=track, engine_version="position-test", fingerprint=fingerprint, params={})
        assert cached["id"] == run
        summary = repo.get_feature_summary(manual["run_id"])
        import json
        assert json.loads(summary["beat_times_json"]) == times
        assert repo.get_candidate(copied["id"])["comment"] == "Keep me"
    # A second manual addition preserves the first, and neither is auto-accepted.
    second = client.post(endpoint, headers=auth(), json={"track_id": track, "target": "OUTRO", "time_ms": 20000, "snap_to": "BAR"})
    assert second.status_code == 201 and len(candidates(client, jobs[0])) == 4
    assert candidates(client, jobs[1]) == previous


def test_manual_invalid_track_or_running_job_changes_nothing(cue_history):
    client, jobs, track, _, _, _, _ = cue_history
    before = candidates(client, jobs[0])
    endpoint = f"/api/v1/jobs/{jobs[0]}/candidates/manual"
    assert client.post(endpoint, headers=auth(), json={"track_id": "wrong", "target": "VOCAL_START", "time_ms": 1000}).status_code == 409
    assert client.post(endpoint, headers=auth(), json={"track_id": track, "target": "FAKE", "time_ms": 1000}).status_code == 422
    with Repository(get_settings().db_path) as repo:
        repo.set_job_status(jobs[0], "RUNNING")
    assert client.post(endpoint, headers=auth(), json={"track_id": track, "target": "VOCAL_START", "time_ms": 1000}).status_code == 409
    assert candidates(client, jobs[0]) == before


def test_concurrent_manual_additions_both_survive_without_changing_other_history(cue_history):
    from concurrent.futures import ThreadPoolExecutor
    client, jobs, track, _, _, _, _ = cue_history
    previous = candidates(client, jobs[1])
    def add(index):
        with Repository(get_settings().db_path) as repo:
            return repo.add_manual_candidate(jobs[0], track, {"type": "VOCAL_START", "time_ms": 1137 + index * 500, "beat": 2 + index, "evidence": []})
    with ThreadPoolExecutor(max_workers=2) as pool:
        added = list(pool.map(add, (0, 1)))
    rows = candidates(client, jobs[0])
    assert len(rows) == 4 and sum(c["type"] == "VOCAL_START" for c in rows) == 2
    assert len(added) == 2
    assert candidates(client, jobs[1]) == previous
