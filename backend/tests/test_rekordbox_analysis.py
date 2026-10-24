from __future__ import annotations

import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.analysis.pipeline import analyze_waveform
from app.analysis.synth import synthesize_edm
from app.api import routes_rekordbox
from app.domain.enums import BeatSource
from app.domain.models import BeatGrid
from app.jobs import worker
from app.main import app
from app.rekordbox import reader
from helpers import write_wav


class AnalysisFile:
    def __init__(self, tags):
        self.tags = tags

    def get_tag(self, name):
        return self.tags[name]

    def get(self, name):
        raise AssertionError("Use get_tag: get(PQTZ) returns arrays, not raw entries")


@pytest.fixture
def analyzed_track(tmp_path, monkeypatch):
    track = synthesize_edm(bpm=120.0, sr=8000)
    wav = write_wav(tmp_path / "analyzed.wav", track.y, track.sr)
    entries = [SimpleNamespace(beat=(i + 2) % 4 + 1, tempo=12000, time=137 + i * 500 + (i // 32) * 10) for i in range(384)]
    phrases = [SimpleNamespace(beat=b) for b in (3, 27, 59, 99, 163, 227, 291)]
    files = {
        "track.DAT": AnalysisFile({"PQTZ": SimpleNamespace(content=SimpleNamespace(entries=entries))}),
        "track.EXT": AnalysisFile({"PSSI": SimpleNamespace(content=SimpleNamespace(entries=phrases, mood=1))}),
    }
    content = SimpleNamespace(ID="RB-ANALYZED", Title="Analyzed track", FolderPath=str(wav), BPM=12000, KeyName="Fm")
    library = SimpleNamespace(
        get_content=lambda **kwargs: content if kwargs.get("ID") == content.ID else None,
        get_anlz_paths=lambda c: {"DAT": "track.DAT", "EXT": "track.EXT"},
        get_cue=lambda **kwargs: [SimpleNamespace(InMsec=25137, Kind=0, Comment="Existing cue")],
    )
    monkeypatch.setattr(reader, "_parse_anlz", lambda path: files.get(path))

    @contextmanager
    def open_library(**kwargs):
        yield library

    monkeypatch.setattr(routes_rekordbox, "open_rekordbox", open_library)
    monkeypatch.setattr(worker, "open_rekordbox", open_library)
    return track, wav, entries, files, library


def _auth():
    return {"Authorization": f"Bearer {app.state.token}"}


def _submit(client, wav):
    response = client.post("/api/v1/jobs", headers=_auth(), json={
        "params": {"analysis_source": "REKORDBOX", "beats_per_phrase": 8, "bpm": 90},
        "tracks": [{"content_id": "RB-ANALYZED", "path": str(wav)}],
    })
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    for _ in range(200):
        job = client.get(f"/api/v1/jobs/{job_id}", headers=_auth()).json()
        if job["status"] in {"COMPLETED", "FAILED"}:
            return job_id, job
        time.sleep(.05)
    raise AssertionError("job did not finish")


def _candidates(client, job_id):
    return client.get(f"/api/v1/jobs/{job_id}/candidates", headers=_auth()).json()["candidates"]


def test_reads_exact_anlz_beats_downbeats_and_phrase_indices(analyzed_track):
    _, wav, entries, _, library = analyzed_track
    data = reader.load_track_analysis(library, "RB-ANALYZED", str(wav))
    assert data["beat_times"] == [e.time / 1000 for e in entries]
    assert data["downbeat_indices"][:3] == [2, 6, 10]
    assert data["phrase_boundaries"][:3] == [2, 26, 58]
    assert data["key"] == "Fm"
    assert data["existing_cues"][0]["time_ms"] == 25137


def test_pipeline_uses_exact_shifted_variable_grid_without_reestimating(analyzed_track, monkeypatch):
    from app.analysis import pipeline

    track, _, entries, _, _ = analyzed_track

    def forbidden(*args, **kwargs):
        raise AssertionError("Must use rekordbox's grid")

    monkeypatch.setattr(pipeline, "estimate_beatgrid", forbidden)
    monkeypatch.setattr(pipeline, "uniform_beatgrid", forbidden)
    grid = BeatGrid(120.0, tuple(e.time / 1000 for e in entries), tuple(range(2, len(entries), 4)), BeatSource.ANLZ)
    result = analyze_waveform(track.y, track.sr, bpm=90, beatgrid=grid, beats_per_phrase=8, phrase_boundaries=(2, 26, 58, 98))
    assert result.beatgrid.beat_times[0] == .137
    assert result.beatgrid.bpm == 120
    assert result.candidates
    assert all(c.beat_index % 4 == 2 for c in result.candidates)
    assert all(c.time_sec == entries[c.beat_index].time / 1000 for c in result.candidates)


def test_analysis_preview_exposes_summary_not_full_grid(analyzed_track):
    _, wav, _, _, _ = analyzed_track
    with TestClient(app) as client:
        response = client.get("/api/v1/rekordbox/tracks/RB-ANALYZED/analysis", params={"path": str(wav)}, headers=_auth())
        assert response.status_code == 200
        data = response.json()
        assert data["available"] and data["beat_count"] == 384 and data["phrase_count"] == 7
        assert "beat_times" not in data
        assert client.get("/api/v1/rekordbox/tracks/RB-ANALYZED/analysis").status_code == 401
        mismatch = client.get("/api/v1/rekordbox/tracks/RB-ANALYZED/analysis", params={"path": str(wav) + ".other"}, headers=_auth()).json()
        assert mismatch["available"] is False


def test_worker_saves_rekordbox_source_and_generates_grid_aligned_candidates(analyzed_track):
    _, wav, entries, _, _ = analyzed_track
    with TestClient(app) as client:
        job_id, job = _submit(client, wav)
        assert job["failed"] == 0
        candidates = _candidates(client, job_id)
        assert candidates and all(c["time_ms"] == entries[c["beat"]].time for c in candidates)
        tracks = client.get(f"/api/v1/jobs/{job_id}/tracks", headers=_auth()).json()["tracks"]
        source = tracks[0]["analysis"]
        assert source["source"] == "REKORDBOX" and source["beat_source"] == "ANLZ"
        assert source["phrase_used"] is True and source["key"] == "Fm"
        assert source["bpm"] == 120 and len(source["existing_cues"]) == 1


def test_changed_rekordbox_grid_has_own_history_and_cache(analyzed_track):
    _, wav, entries, _, _ = analyzed_track
    with TestClient(app) as client:
        first, _ = _submit(client, wav)
        original = _candidates(client, first)
        client.post(f"/api/v1/candidates/{original[0]['id']}/decision", headers=_auth(), json={"accepted": True})
        for entry in entries:
            entry.time += 125
        second, job = _submit(client, wav)
        assert job["failed"] == 0
        updated = _candidates(client, second)
        assert {c["id"] for c in original}.isdisjoint(c["id"] for c in updated)
        assert {c["id"] for c in _candidates(client, first)} == {c["id"] for c in original}
        assert all(c["accepted"] is None for c in updated)
        third, _ = _submit(client, wav)
        assert {c["id"] for c in _candidates(client, third)} == {c["id"] for c in updated}
        plan = client.post("/api/v1/write/plan", headers=_auth(), json={"job_id": second}).json()
        assert plan["items"] == []


def test_changed_downbeat_labels_are_used_without_changing_beat_times(analyzed_track):
    _, wav, entries, _, _ = analyzed_track
    with TestClient(app) as client:
        first, job = _submit(client, wav)
        assert job["failed"] == 0
        original = _candidates(client, first)
        assert original and all(c["beat"] % 4 == 2 for c in original)
        original_times = [entry.time for entry in entries]
        # rekordbox で拍時刻を動かさず、小節内の「1拍目」だけを変更した場合。
        for entry in entries:
            entry.beat = entry.beat % 4 + 1
        second, job = _submit(client, wav)
        assert job["failed"] == 0
        updated = _candidates(client, second)
        assert updated and all(c["beat"] % 4 == 1 for c in updated)
        assert all(c["time_ms"] == original_times[c["beat"]] for c in updated)
        assert {c["id"] for c in original}.isdisjoint(c["id"] for c in updated)
        assert {c["id"] for c in _candidates(client, first)} == {c["id"] for c in original}
        assert [entry.time for entry in entries] == original_times


def test_missing_grid_stops_rekordbox_mode_without_audio_fallback(analyzed_track):
    _, wav, _, files, _ = analyzed_track
    files["track.DAT"].tags.clear()
    with TestClient(app) as client:
        preview = client.get("/api/v1/rekordbox/tracks/RB-ANALYZED/analysis", headers=_auth()).json()
        assert preview["available"] is False
        job_id, job = _submit(client, wav)
        assert job["failed"] == 1 and _candidates(client, job_id) == []
        data = client.get(f"/api/v1/jobs/{job_id}/tracks", headers=_auth()).json()["tracks"][0]["analysis"]
        assert data["available"] is False and "BPM / Grid" in data["reason"]


def test_missing_phrase_uses_rekordbox_grid_with_explicit_warning(analyzed_track):
    _, wav, entries, files, _ = analyzed_track
    files["track.EXT"].tags.clear()
    with TestClient(app) as client:
        job_id, job = _submit(client, wav)
        assert job["failed"] == 0
        candidates = _candidates(client, job_id)
        assert candidates and all(c["time_ms"] == entries[c["beat"]].time for c in candidates)
        data = client.get(f"/api/v1/jobs/{job_id}/tracks", headers=_auth()).json()["tracks"][0]["analysis"]
        assert data["phrase_used"] is False and data["warnings"]


def test_reader_tries_next_analysis_file_when_tag_is_missing(analyzed_track):
    _, wav, _, files, library = analyzed_track
    files["track.EXT"].tags["PQTZ"] = files["track.DAT"].tags.pop("PQTZ")
    assert reader.load_track_analysis(library, "RB-ANALYZED", str(wav))["beat_count"] == 384


def test_library_adapter_enforces_read_only_connection(monkeypatch):
    import pyrekordbox
    from app.rekordbox.adapter import open_rekordbox

    statements = []
    closed = []
    database = SimpleNamespace(session=SimpleNamespace(execute=lambda statement: statements.append(str(statement))), close=lambda: closed.append(True))
    monkeypatch.setattr(pyrekordbox, "Rekordbox6Database", lambda **kwargs: database)
    with open_rekordbox() as opened:
        assert opened is database
        assert statements == ["PRAGMA query_only=ON"]
    assert closed == [True]


def test_requested_purpose_candidates_are_unaccepted_and_export_after_review(analyzed_track):
    import xml.etree.ElementTree as ET
    _, wav, entries, files, _ = analyzed_track
    phrase = files["track.EXT"].tags["PSSI"].content
    phrase.mood = 2
    phrase.end_beat = 383
    phrase.entries = [SimpleNamespace(beat=beat, kind=kind) for beat, kind in [(3, 1), (35, 2), (67, 9), (131, 2), (163, 9), (227, 10)]]
    targets = ["INTRO_START", "OUTRO", "CHORUS_START", "CHORUS_END", "CHORUS_END_MINUS_8_BARS", "VOCAL_START"]
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", headers=_auth(), json={"params": {"analysis_source": "REKORDBOX", "cue_targets": targets}, "tracks": [{"content_id": "RB-ANALYZED", "path": str(wav)}]})
        assert response.status_code == 201
        job_id = response.json()["job_id"]
        for _ in range(200):
            job = client.get(f"/api/v1/jobs/{job_id}", headers=_auth()).json()
            if job["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(.05)
        assert job["failed"] == 0 and job["params"]["cue_targets"] == targets
        rows = _candidates(client, job_id)
        assert {c["type"] for c in rows} == set(targets)
        assert all(c["accepted"] is None and c["time_ms"] == entries[c["beat"]].time for c in rows)
        before = [c for c in rows if c["type"] == "CHORUS_END_MINUS_8_BARS"]
        assert [c["beat"] for c in before] == [98, 194]
        source = client.get(f"/api/v1/jobs/{job_id}/tracks", headers=_auth()).json()["tracks"][0]["analysis"]
        assert source["section_labels_used"] and any("仮候補" in warning for warning in source["warnings"])
        # Candidate creation is separate from adoption and never exports existing cues.
        assert client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id}).status_code == 400
        client.post(f"/api/v1/candidates/{before[0]['id']}/decision", headers=_auth(), json={"accepted": True, "cue_kind": "BOTH"})
        result = client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id})
        assert result.status_code == 200 and result.json()["cues"] == 2
        marks = ET.parse(result.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
        assert all(mark.get("Name") == "サビの終わりから8小節前" for mark in marks)
        assert {mark.get("Num") for mark in marks} == {"-1", "0"}
