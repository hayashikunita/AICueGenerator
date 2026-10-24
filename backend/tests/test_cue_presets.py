import wave
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.common import new_id
from app.config import get_settings
from app.domain.cue_targets import PURPOSE_TARGETS
from app.main import app
from app.persistence.repositories import Repository
from app.schemas.jobs import JobParams


def auth():
    return {"Authorization": f"Bearer {app.state.token}"}


@pytest.fixture
def preset_job(tmp_path):
    path = tmp_path / "presets.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * 12)
    original = path.read_bytes()
    params = JobParams(cue_targets=list(PURPOSE_TARGETS), end_alignment_bars=8,
        cue_default={"cue_kind": "HOT", "memory_color": "#ffff00", "hot_color": "#ff0000"},
        cue_settings={"INTRO_START": {"cue_kind": "MEMORY", "memory_color": "#00ff00", "hot_color": "#ff0000"},
                      "INTRO_END": {"cue_kind": "BOTH", "memory_color": None, "hot_color": "#0000ff"},
                      "OUTRO_END": {"cue_kind": "MEMORY", "memory_color": "#9900ff", "hot_color": "#ff0000"}}).model_dump()
    with TestClient(app) as client, Repository(get_settings().db_path) as repo:
        track = repo.upsert_track(content_id=new_id(), path=str(path), fmt="WAV")
        run = repo.create_run(track_id=track, engine_version="preset-test", params=params, fingerprint=new_id(), beat_source="ANLZ", pssi_used=True)
        types = list(PURPOSE_TARGETS)
        ids = repo.add_candidates(run, [{"type": target, "time_ms": index * 1000, "confidence": 85, "rank": 1} for index, target in enumerate(types)])
        job = repo.create_job(params=params, track_ids=[track])
        repo.set_job_status(job, "COMPLETED")
        repo.set_job_track_analysis(job, track, {"available": True}, run)
        yield client, repo, job, run, dict(zip(types, ids))
    assert path.read_bytes() == original


def test_presets_wait_for_review_then_apply_mixed_kinds_and_xml_colors(preset_job):
    client, repo, job, _, ids = preset_job
    assert all(row["accepted"] is None for row in repo.list_candidates_for_job(job))
    response = client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=auth(), json={"candidate_ids": list(ids.values()), "cue_kind": "PRESET"})
    assert response.status_code == 200, response.text
    rows = {r["type"]: r for r in response.json()["candidates"]}
    assert rows["INTRO_START"]["cue_kind"] == "MEMORY"
    assert rows["INTRO_END"]["cue_kind"] == "BOTH"
    assert rows["OUTRO_END"]["cue_kind"] == "MEMORY"
    assert rows["CHORUS_START"]["cue_kind"] == "HOT"
    plan = client.post("/api/v1/write/plan", headers=auth(), json={"job_id": job}).json()
    assert plan["add"] == 9 and all(item["preset"] for item in plan["items"])
    exported = client.post("/api/v1/write/export-xml", headers=auth(), json={"job_id": job, "cue_colors": {"MEMORY": "#ffffff", "HOT": "#ffffff"}})
    assert exported.status_code == 200, exported.text
    data = exported.json()
    assert data["cues"] == 9 and data["cue_settings_used"] is True
    marks = ET.parse(data["xml_path"]).getroot().findall(".//POSITION_MARK")
    for mark in marks:
        if mark.get("Name") == "イントロの終わり" and mark.get("Num") == "-1":
            assert all(mark.get(key) is None for key in ("Red", "Green", "Blue"))
        else:
            expected = (0, 255, 0) if mark.get("Name") == "イントロの始まり" else (153, 0, 255) if mark.get("Name") == "アウトロの終わり" else (0, 0, 255) if mark.get("Name") == "イントロの終わり" else (255, 0, 0)
            assert tuple(int(mark.get(key)) for key in ("Red", "Green", "Blue")) == expected
    assert len({m.get("Num") for m in marks if m.get("Num") != "-1"}) == 6


def test_preset_bulk_hot_overflow_is_atomic(preset_job):
    client, repo, job, run, _ = preset_job
    extra = repo.add_candidates(run, [{"type": "CHORUS_START", "time_ms": i * 1000, "confidence": 80, "rank": i + 1} for i in range(9)])
    result = client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=auth(), json={"candidate_ids": extra, "cue_kind": "PRESET"})
    assert result.status_code == 409 and "8件" in result.json()["detail"]
    assert all(row["accepted"] is None for row in repo.list_candidates_for_job(job))


def test_individual_kind_override_keeps_per_target_colors(preset_job):
    client, _, job, _, ids = preset_job
    response = client.post(f"/api/v1/candidates/{ids['INTRO_END']}/decision", headers=auth(), json={"accepted": True, "cue_kind": "HOT", "edited_time_ms": 1500})
    assert response.status_code == 200
    exported = client.post("/api/v1/write/export-xml", headers=auth(), json={"job_id": job}).json()
    marks = ET.parse(exported["xml_path"]).getroot().findall(".//POSITION_MARK")
    assert len(marks) == 1 and marks[0].get("Start") == "1.5"
    assert tuple(int(marks[0].get(key)) for key in ("Red", "Green", "Blue")) == (0, 0, 255)


@pytest.mark.parametrize("params", [
    {"end_alignment_bars": 2}, {"cue_default": {"cue_kind": "OTHER"}},
    {"cue_settings": {"INVALID": {"cue_kind": "HOT"}}},
    {"cue_default": {"memory_color": "red"}}, {"cue_default": {"hot_color": None}},
])
def test_invalid_presets_are_rejected(params):
    with TestClient(app) as client:
        result = client.post("/api/v1/jobs", headers=auth(), json={"params": params, "tracks": [{"content_id": "file", "path": "test.wav"}]})
        assert result.status_code == 422
