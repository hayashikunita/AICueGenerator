import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.common import new_id
from app.config import get_settings
from app.main import app
from app.persistence.repositories import Repository


SCORES = [10, 95, 20, 85, 70, 65, 40, 90, 75, 60, 55, 100, 15, 80, 50]
TOP_TEN = {1, 3, 4, 5, 7, 8, 9, 10, 11, 13}


def auth():
    return {"Authorization": f"Bearer {app.state.token}"}


@pytest.fixture
def memory_job(tmp_path):
    originals = []
    with TestClient(app) as client, Repository(get_settings().db_path) as repo:
        tracks, runs, groups = [], [], []
        for index in range(2):
            path = tmp_path / f"memory-{index}.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(bytes([index, 0]) * 8000 * 16)
            originals.append((path, path.read_bytes()))
            track = repo.upsert_track(content_id=new_id(), path=str(path), fmt="WAV")
            run = repo.create_run(track_id=track, engine_version="memory-limit-test", params={}, fingerprint=new_id(), beat_source="ANLZ", pssi_used=True)
            ids = repo.add_candidates(run, [{"type": "CHORUS_START", "time_ms": i * 1000, "beat": i * 2, "confidence": score, "rank": i + 1} for i, score in enumerate(SCORES if index == 0 else SCORES[::-1])])
            repo.finish_run(run, status="COMPLETED")
            tracks.append(track)
            runs.append(run)
            groups.append(ids)
        job = repo.create_job(params={}, track_ids=tracks)
        repo.set_job_status(job, "COMPLETED")
        for track, run in zip(tracks, runs):
            repo.set_job_track_analysis(job, track, {"available": True, "source": "REKORDBOX"}, run)
            repo.set_job_track_status(job, track, "COMPLETED")
        response = client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=auth(), json={"candidate_ids": sum(groups, []), "cue_kind": "MEMORY"})
        assert response.status_code == 200, response.text
        assert len([c for c in response.json()["candidates"] if c["accepted"]]) == 30
        yield client, repo, job, tracks, groups
    assert all(path.read_bytes() == original for path, original in originals)


def exported(client, job, **selection):
    return client.post("/api/v1/write/export-xml", headers=auth(), json={"job_id": job, **selection})


def snapshot(repo, job):
    return [dict(row) for row in repo.list_candidates_for_job(job)]


def test_auto_export_uses_ten_highest_confidence_per_track_but_keeps_thirty_accepted(memory_job):
    client, repo, job, _, _ = memory_job
    before = snapshot(repo, job)
    response = exported(client, job)
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["tracks"], data["cues"]) == (2, 20)
    tracks = ET.parse(data["xml_path"]).getroot().find("COLLECTION").findall("TRACK")
    by_name = {track.get("Name"): track for track in tracks}
    assert {int(float(mark.get("Start"))) for mark in by_name["memory-0"].findall("POSITION_MARK")} == TOP_TEN
    assert {int(float(mark.get("Start"))) for mark in by_name["memory-1"].findall("POSITION_MARK")} == {14 - i for i in TOP_TEN}
    assert all(len(track.findall("POSITION_MARK")) == 10 for track in tracks)
    assert any("10件" in warning and "採用状態は変更していません" in warning for warning in data["warnings"])
    assert snapshot(repo, job) == before
    plan = client.post("/api/v1/write/plan", headers=auth(), json={"job_id": job})
    assert plan.status_code == 200 and plan.json()["add"] == 20


def test_explicit_export_selection_can_replace_auto_choices_without_saving_decisions(memory_job):
    client, repo, job, _, groups = memory_job
    before = snapshot(repo, job)
    selected = groups[0][:10] + groups[1][-10:]
    response = exported(client, job, memory_candidate_ids=selected)
    assert response.status_code == 200, response.text
    tracks = ET.parse(response.json()["xml_path"]).getroot().find("COLLECTION").findall("TRACK")
    by_name = {track.get("Name"): track for track in tracks}
    assert {float(mark.get("Start")) for mark in by_name["memory-0"].findall("POSITION_MARK")} == set(range(10))
    assert {float(mark.get("Start")) for mark in by_name["memory-1"].findall("POSITION_MARK")} == set(range(5, 15))
    plan = client.post("/api/v1/write/plan", headers=auth(), json={"job_id": job, "memory_candidate_ids": selected}).json()
    assert plan["add"] == 20
    assert {item["time_ms"] for item in plan["items"]} == set(range(0, 15000, 1000))
    assert snapshot(repo, job) == before


def test_excluding_memory_half_of_both_keeps_hot_half(memory_job):
    client, repo, job, _, groups = memory_job
    repo.upsert_decision(candidate_id=groups[0][0], accepted=True, cue_kind="BOTH", edited_time_ms=125, slot="H", comment="Keep both accepted")
    before = snapshot(repo, job)
    response = exported(client, job)
    assert response.status_code == 200
    assert response.json()["cues"] == 21
    tracks = ET.parse(response.json()["xml_path"]).getroot().find("COLLECTION").findall("TRACK")
    first = next(track for track in tracks if track.get("Name") == "memory-0")
    marks = first.findall("POSITION_MARK")
    assert len([m for m in marks if m.get("Num") == "-1"]) == 10
    assert any(m.get("Num") == "7" and float(m.get("Start")) == .125 for m in marks)
    assert not any(m.get("Num") == "-1" and float(m.get("Start")) == .125 for m in marks)
    assert snapshot(repo, job) == before
    only_hot = exported(client, job, memory_candidate_ids=[])
    assert only_hot.status_code == 200 and only_hot.json()["cues"] == 1


@pytest.mark.parametrize("invalid", ["eleven", "duplicate", "outside", "empty"])
def test_invalid_selection_leaves_prior_export_and_decisions_untouched(memory_job, invalid):
    client, repo, job, _, groups = memory_job
    previous = exported(client, job).json()
    xml = Path(previous["xml_path"])
    original = xml.read_bytes()
    output_files = set(get_settings().export_dir.rglob("*"))
    before = snapshot(repo, job)
    selected = {"eleven": groups[0][:11], "duplicate": [groups[0][0], groups[0][0]], "outside": ["outside-job"], "empty": []}[invalid]
    response = exported(client, job, memory_candidate_ids=selected)
    assert response.status_code == 400, response.text
    if invalid == "eleven":
        assert "11件" in response.json()["detail"] and "10件" in response.json()["detail"]
    assert xml.read_bytes() == original
    assert set(get_settings().export_dir.rglob("*")) == output_files
    assert snapshot(repo, job) == before
