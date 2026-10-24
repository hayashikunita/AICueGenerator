from __future__ import annotations

import wave
import xml.etree.ElementTree as ET
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.common import new_id
from app.config import get_settings
from app.main import app
from app.persistence.repositories import Repository


@pytest.fixture
def cue_job(tmp_path):
    audio_path = tmp_path / "cue_modes.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000)
    with TestClient(app) as client:
        with Repository(get_settings().db_path) as repo:
            track_id = repo.upsert_track(content_id=new_id(), path=str(audio_path), fmt="WAV")
            job_id = repo.create_job(params={}, track_ids=[track_id])
            repo.set_job_status(job_id, "COMPLETED")
            run_id = repo.create_run(
                track_id=track_id, engine_version="test", params={}, fingerprint=new_id(),
                beat_source="test", pssi_used=False,
            )
            ids = repo.add_candidates(run_id, [
                {"type": "DROP", "time_ms": (i + 1) * 100, "confidence": 90, "rank": i + 1}
                for i in range(9)
            ])
        yield client, job_id, ids


def _auth():
    return {"Authorization": f"Bearer {app.state.token}"}


def _decide(client, candidate_id, kind, **kwargs):
    result = client.post(
        f"/api/v1/candidates/{candidate_id}/decision", headers=_auth(),
        json={"accepted": True, "cue_kind": kind, **kwargs},
    )
    assert result.status_code == 200, result.text


def _export(client, job_id):
    return client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id})


def test_memory_hot_and_both_persist_and_export_together(cue_job):
    client, job_id, ids = cue_job
    _decide(client, ids[0], "MEMORY")
    _decide(client, ids[1], "HOT")
    _decide(client, ids[2], "BOTH", slot="H", edited_time_ms=0)

    candidates = client.get(f"/api/v1/jobs/{job_id}/candidates", headers=_auth()).json()["candidates"]
    assert [c["cue_kind"] for c in candidates[:3]] == ["MEMORY", "HOT", "BOTH"]
    assert all(c["accepted"] for c in candidates[:3])
    assert client.get(f"/api/v1/candidates/{ids[2]}", headers=_auth()).json()["cue_kind"] == "BOTH"
    with Repository(get_settings().db_path) as repo:
        assert repo.get_candidate(ids[2])["cue_kind"] == "BOTH"

    plan = client.post("/api/v1/write/plan", headers=_auth(), json={"job_id": job_id}).json()
    assert plan["add"] == 4 and plan["conflict"] == 0
    assert sorted(i["cue_kind"] for i in plan["items"]) == ["HOT", "HOT", "MEMORY", "MEMORY"]
    pair = [i for i in plan["items"] if i["time_ms"] == 0]
    assert {(i["cue_kind"], i["slot"]) for i in pair} == {("MEMORY", None), ("HOT", "H")}

    response = _export(client, job_id)
    assert response.status_code == 200, response.text
    assert response.json()["cues"] == 4
    marks = ET.parse(response.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
    assert sorted(int(m.get("Num")) for m in marks) == [-1, -1, 0, 7]
    assert {m.get("Num") for m in marks if float(m.get("Start")) == 0} == {"-1", "7"}

    # 「両方」から片方へ戻した場合、以前の Hot Cue を残さない。
    _decide(client, ids[2], "MEMORY")
    updated = _export(client, job_id)
    assert updated.status_code == 200
    assert updated.json()["cues"] == 3
    marks = ET.parse(updated.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
    assert sorted(int(m.get("Num")) for m in marks) == [-1, -1, 0]


@pytest.mark.parametrize(("kind", "count", "expected"), [("MEMORY", 9, 9), ("HOT", 8, 8), ("BOTH", 8, 16)])
def test_cue_limits_count_hot_separately(cue_job, kind, count, expected):
    client, job_id, ids = cue_job
    for candidate_id in ids[:count]:
        _decide(client, candidate_id, kind)
    result = _export(client, job_id)
    assert result.status_code == 200, result.text
    assert result.json()["cues"] == expected
    marks = ET.parse(result.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
    hot = [int(m.get("Num")) for m in marks if int(m.get("Num")) >= 0]
    assert hot == ([] if kind == "MEMORY" else list(range(8)))


def test_hot_overflow_preserves_previous_export(cue_job):
    client, job_id, ids = cue_job
    for candidate_id in ids:
        _decide(client, candidate_id, "HOT")
    library = get_settings().export_dir / datetime.now().strftime("%Y%m%d")
    library.mkdir(parents=True, exist_ok=True)
    xml_path = library / "rekordbox.xml"
    xml_path.write_text("previous export", encoding="utf-8")
    result = _export(client, job_id)
    assert result.status_code == 400
    assert "8" in result.json()["detail"]
    assert xml_path.read_text(encoding="utf-8") == "previous export"
    _decide(client, ids[-1], "MEMORY")
    assert _export(client, job_id).status_code == 200


def test_duplicate_hot_slots_are_rejected(cue_job):
    client, job_id, ids = cue_job
    _decide(client, ids[0], "HOT", slot="A")
    _decide(client, ids[1], "BOTH", slot="A")
    result = _export(client, job_id)
    assert result.status_code == 400
    assert "重複" in result.json()["detail"]


def test_kind_colors_export_separately_for_memory_hot_and_both(cue_job):
    client, job_id, ids = cue_job
    _decide(client, ids[0], "MEMORY")
    _decide(client, ids[1], "HOT")
    _decide(client, ids[2], "BOTH", slot="H", edited_time_ms=0)
    palette = {"MEMORY": "#112233", "HOT": "#FfAa00"}
    response = client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id, "cue_colors": palette})
    assert response.status_code == 200, response.text
    assert response.json()["cue_colors"] == palette
    assert any("未確認" in warning for warning in response.json()["warnings"])
    marks = ET.parse(response.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
    assert len(marks) == 4
    for mark in marks:
        actual = tuple(int(mark.get(key)) for key in ("Red", "Green", "Blue"))
        expected = (17, 34, 51) if mark.get("Num") == "-1" else (255, 170, 0)
        assert actual == expected
    pair = [m for m in marks if float(m.get("Start")) == 0]
    assert {m.get("Num") for m in pair} == {"-1", "7"}
    # Changing only the export palette keeps saved decisions, times and slots.
    updated = client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id, "cue_colors": {"MEMORY": "#ffffff", "HOT": "#000000"}})
    assert updated.status_code == 200
    newer = ET.parse(updated.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
    assert [(m.get("Start"), m.get("Num")) for m in newer] == [(m.get("Start"), m.get("Num")) for m in marks]
    for mark in newer:
        assert {mark.get(key) for key in ("Red", "Green", "Blue")} == ({"255"} if mark.get("Num") == "-1" else {"0"})


@pytest.mark.parametrize("palette", [
    {"MEMORY": "red", "HOT": "#ffffff"}, {"MEMORY": "#123", "HOT": "#ffffff"},
    {"MEMORY": "#123456", "HOT": "#gggggg"}, {"HOT": "#ffffff"},
    {"MEMORY": None, "HOT": "#ffffff"},
])
def test_invalid_export_colors_leave_previous_output_untouched(cue_job, palette):
    client, job_id, ids = cue_job
    _decide(client, ids[0], "BOTH")
    response = _export(client, job_id)
    path = get_settings().export_dir / datetime.now().strftime("%Y%m%d") / "rekordbox.xml"
    previous = path.read_bytes()
    invalid = client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id, "cue_colors": palette})
    assert response.status_code == 200 and invalid.status_code == 422
    assert path.read_bytes() == previous


def test_legacy_export_remains_without_rgb_and_requires_auth(cue_job):
    client, job_id, ids = cue_job
    _decide(client, ids[0], "BOTH")
    denied = client.post("/api/v1/write/export-xml", json={"job_id": job_id, "cue_colors": {"MEMORY": "#112233", "HOT": "#ffaa00"}})
    assert denied.status_code == 401
    response = _export(client, job_id)
    assert response.status_code == 200
    assert response.json()["cue_colors"] == {} and response.json()["warnings"] == []
    marks = ET.parse(response.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
    assert marks and all("Red" not in mark.attrib for mark in marks)
