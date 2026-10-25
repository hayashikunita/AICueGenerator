from copy import deepcopy
from pathlib import Path
import wave
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.common import new_id
from app.config import get_settings
from app.main import app
from app.persistence.repositories import Repository
from app.rekordbox import existing_export


def auth():
    return {"Authorization": f"Bearer {app.state.token}"}


@pytest.fixture
def existing_job(tmp_path, monkeypatch):
    audio = tmp_path / "Original 日本語 & space.wav"
    with wave.open(str(audio), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(b"\0\0" * (8000 * 20 + 2000))  # XML TotalTime stores only 20 whole seconds.
    original_audio = audio.read_bytes()
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="rekordbox", Version="7.2.19", Company="AlphaTheta")
    collection = ET.SubElement(root, "COLLECTION", Entries="2")
    track = ET.SubElement(collection, "TRACK", TrackID="1234", Name="Registered & title", Artist="Artist", Album="Album", Comments="Keep this", Genre="Pop", Tonality="Am", Rating="204", TotalTime="20", Location=audio.as_uri())
    ET.SubElement(track, "TEMPO", Inizio="0.0", Bpm="120.00", Metro="4/4", Battito="1")
    ET.SubElement(track, "TEMPO", Inizio="8.0", Bpm="120.00", Metro="4/4", Battito="1")
    ET.SubElement(track, "POSITION_MARK", Name="Existing memory", Type="0", Start="0.5", Num="-1", Red="17", Green="34", Blue="51")
    ET.SubElement(track, "POSITION_MARK", Name="Existing hot A", Type="0", Start="2.0", Num="0", Red="0", Green="17", Blue="34")
    ET.SubElement(track, "POSITION_MARK", Name="Keep loop", Type="4", Start="4.0", End="6.0", Num="-1", Red="255", Green="0", Blue="0")
    ET.SubElement(collection, "TRACK", TrackID="9999", Name="Unrelated", Location=(tmp_path / "other.wav").as_uri())
    playlists = ET.SubElement(root, "PLAYLISTS")
    folder = ET.SubElement(playlists, "NODE", Name="ROOT", Type="0", Count="1")
    playlist = ET.SubElement(folder, "NODE", Name="Original playlist", Type="1", KeyType="0", Entries="1")
    ET.SubElement(playlist, "TRACK", Key="1234")
    source_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    baseline = tmp_path / "collection.xml"
    baseline.write_bytes(source_bytes)
    with TestClient(app) as client, Repository(get_settings().db_path) as repo:
        # A non-numeric test ID prevents tests from consulting the live library.
        tid = repo.upsert_track(content_id=new_id(), path=str(audio), fmt="WAV")
        run = repo.create_run(track_id=tid, engine_version="existing-test", params={}, fingerprint=new_id(), beat_source="ANLZ", pssi_used=True)
        spec = [("INTRO_START", 500, "MEMORY"), ("INTRO_END", 1000, "MEMORY"), ("CHORUS_START", 3000, "HOT"), ("CHORUS_END", 7000, "BOTH"), ("OUTRO", 9000, "HOT")]
        ids = repo.add_candidates(run, [{"type": target, "time_ms": ms, "confidence": 85, "rank": 1} for target, ms, _ in spec])
        for candidate, (_, _, kind) in zip(ids, spec):
            repo.upsert_decision(candidate_id=candidate, accepted=True, cue_kind=kind, slot="H" if candidate == ids[-1] else None)
        job = repo.create_job(params={}, track_ids=[tid])
        repo.set_job_status(job, "COMPLETED")
        repo.set_job_track_analysis(job, tid, {"available": True}, run)
        cue_rows = [
            {"ID": "m1", "Kind": 0, "InMsec": 500, "OutMsec": -1, "Comment": "Existing memory", "Color": 1122867, "ActiveLoop": 0},
            {"ID": "h1", "Kind": 1, "InMsec": 2000, "OutMsec": -1, "Comment": "Existing hot A", "Color": 4386, "ActiveLoop": 0},
            {"ID": "loop", "Kind": 0, "InMsec": 4000, "OutMsec": 6000, "Comment": "Keep loop", "Color": 16711680, "ActiveLoop": 0},
        ]
        snapshot = {tid: {"detail": {"title": "Registered & title", "artist": "Artist", "album": "Album", "path": str(audio)}, "cues": cue_rows,
                          "grid": {"available": True, "beat_times": [i * .5 for i in range(40)], "downbeat_indices": list(range(0, 40, 4))}}}
        monkeypatch.setattr(existing_export, "current_tracks", lambda rows: deepcopy(snapshot))
        uploaded = client.post("/api/v1/write/source-xml", headers=auth(), json={"filename": baseline.name, "xml_text": source_bytes.decode()})
        assert uploaded.status_code == 200, uploaded.text
        body = {"job_id": job, "mode": "EXISTING", "source_id": uploaded.json()["source_id"], "cue_colors": {"MEMORY": "#00ff00", "HOT": "#ff0000"}}
        yield client, repo, body, snapshot, tid, ids, track, source_bytes, run
    assert audio.read_bytes() == original_audio
    assert baseline.read_bytes() == source_bytes


def preview(client, body):
    result = client.post("/api/v1/write/plan", headers=auth(), json=body)
    assert result.status_code == 200, result.text
    return result.json()


def test_additive_xml_preserves_original_track_grid_cues_loops_and_slots(existing_job):
    client, repo, body, _, _, _, original_track, source_bytes, _ = existing_job
    before = [dict(row) for row in repo.list_candidates_for_job(body["job_id"])]
    plan = preview(client, body)
    assert (plan["add"], plan["preserved"], plan["duplicates_skipped"], plan["conflict"]) == (5, 3, 1, 0)
    assert plan["track_updates"][0]["existing_memory"] == 2  # Memory Loop uses capacity too.
    response = client.post("/api/v1/write/export-xml", headers=auth(), json={**body, "confirmation_hash": plan["confirmation_hash"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["copied"], result["added_cues"], result["preserved_cues"], result["cues"]) == (0, 5, 3, 8)
    assert Path(result["backup_xml_path"]).read_bytes() == source_bytes
    output = ET.parse(result["xml_path"]).getroot()
    tracks = output.findall("COLLECTION/TRACK")
    assert len(tracks) == 1
    track = tracks[0]
    assert track.attrib == original_track.attrib
    assert [t.attrib for t in track.findall("TEMPO")] == [t.attrib for t in original_track.findall("TEMPO")]
    marks = track.findall("POSITION_MARK")
    assert [m.attrib for m in marks[:3]] == [m.attrib for m in original_track.findall("POSITION_MARK")]
    assert {int(m.get("Num")) for m in marks if int(m.get("Num")) >= 0} == {0, 1, 2, 7}
    assert output.findall("PLAYLISTS/NODE/NODE") == []  # No playlist replacement instructions.
    assert {p.name for p in Path(result["folder"]).iterdir()} == {"rekordbox.xml", "original_collection.xml"}
    assert [dict(row) for row in repo.list_candidates_for_job(body["job_id"])] == before


def test_existing_export_scopes_originals_and_requires_new_confirmation_when_scope_changes(existing_job, tmp_path):
    client, repo, body, snapshot, first, _, original_track, source_bytes, first_run = existing_job
    second_audio = tmp_path / "Second.wav"
    second_audio.write_bytes(Path(snapshot[first]["detail"]["path"]).read_bytes())
    second = repo.upsert_track(content_id=new_id(), path=str(second_audio), fmt="WAV")
    second_run = repo.create_run(track_id=second, engine_version="existing-test", params={}, fingerprint=new_id(), beat_source="ANLZ", pssi_used=True)
    candidate = repo.add_candidates(second_run, [{"type": "INTRO_END", "time_ms": 1500, "confidence": 85, "rank": 1}])[0]
    repo.finish_run(second_run, status="COMPLETED")
    repo.upsert_decision(candidate_id=candidate, accepted=True, cue_kind="MEMORY")
    job = repo.create_job(params={}, track_ids=[first, second])
    repo.set_job_status(job, "COMPLETED")
    for tid, run in ((first, first_run), (second, second_run)):
        repo.set_job_track_analysis(job, tid, {"available": True}, run)
    snapshot[second] = deepcopy(snapshot[first])
    snapshot[second]["detail"]["path"] = str(second_audio)
    root = ET.fromstring(source_bytes)
    second_xml = deepcopy(original_track)
    second_xml.set("TrackID", "5678")
    second_xml.set("Location", second_audio.as_uri())
    root.find("COLLECTION").append(second_xml)
    root.find("COLLECTION").set("Entries", "3")
    uploaded = client.post("/api/v1/write/source-xml", headers=auth(), json={"filename": "two.xml", "xml_text": ET.tostring(root, encoding="unicode")}).json()
    body = {**body, "job_id": job, "source_id": uploaded["source_id"]}
    full_plan = preview(client, body)
    assert {row["track_id"] for row in full_plan["track_updates"]} == {first, second}
    selected = {**body, "track_ids": [second]}
    response = client.post("/api/v1/write/export-xml", headers=auth(), json={**selected, "confirmation_hash": full_plan["confirmation_hash"]})
    assert response.status_code == 400
    # Hidden originals, including their conflicts, must not enter the selected export.
    snapshot[first]["cues"][2]["ActiveLoop"] = 1
    assert preview(client, body)["conflict"] > 0
    plan = preview(client, selected)
    assert plan["conflict"] == 0 and plan["add"] == 1 and plan["preserved"] == 3
    assert {row["track_id"] for row in plan["track_updates"]} == {second}
    response = client.post("/api/v1/write/export-xml", headers=auth(), json={**selected, "confirmation_hash": plan["confirmation_hash"]})
    assert response.status_code == 200, response.text
    output = ET.parse(response.json()["xml_path"]).findall("COLLECTION/TRACK")
    assert len(output) == 1 and output[0].get("Location") == second_audio.as_uri()


@pytest.mark.parametrize("change", ["cue", "grid", "color"])
def test_change_after_preview_requires_confirmation_again(existing_job, change):
    client, _, body, snapshot, tid, _, _, _, _ = existing_job
    plan = preview(client, body)
    if change == "cue":
        snapshot[tid]["cues"][0]["Comment"] = "Changed in rekordbox"
    elif change == "grid":
        snapshot[tid]["grid"]["beat_times"] = [t + .02 for t in snapshot[tid]["grid"]["beat_times"]]
    else:
        snapshot[tid]["cues"][0]["Color"] = 255
    response = client.post("/api/v1/write/export-xml", headers=auth(), json={**body, "confirmation_hash": plan["confirmation_hash"]})
    assert response.status_code == 400, response.text


def test_existing_hot_slot_is_not_overwritten(existing_job):
    client, repo, body, _, _, ids, _, _, _ = existing_job
    repo.upsert_decision(candidate_id=ids[2], accepted=True, cue_kind="HOT", slot="A")
    plan = preview(client, body)
    assert plan["conflict"] > 0
    assert any("使用済み" in reason for reason in plan["issues"])
    response = client.post("/api/v1/write/export-xml", headers=auth(), json={**body, "confirmation_hash": plan["confirmation_hash"]})
    assert response.status_code == 400


def test_existing_memory_capacity_is_counted_without_trimming_existing_cues(existing_job):
    client, repo, body, _, _, ids, _, _, run = existing_job
    for candidate in ids:
        repo.upsert_decision(candidate_id=candidate, accepted=False, cue_kind="MEMORY")
    extra = repo.add_candidates(run, [{"type": "INTRO_END", "time_ms": 10000 + i * 500, "confidence": 90, "rank": i + 1} for i in range(9)])
    for candidate in extra:
        repo.upsert_decision(candidate_id=candidate, accepted=True, cue_kind="MEMORY")
    plan = preview(client, body)
    assert plan["preserved"] == 3 and plan["add"] == 8 and plan["conflict"] > 0
    response = client.post("/api/v1/write/export-xml", headers=auth(), json={**body, "confirmation_hash": plan["confirmation_hash"]})
    assert response.status_code == 400


def test_active_loop_stale_xml_and_ambiguous_paths_block_update(existing_job):
    client, _, body, snapshot, tid, _, original, source_bytes, _ = existing_job
    snapshot[tid]["cues"][2]["ActiveLoop"] = 1
    assert any("アクティブループ" in issue for issue in preview(client, body)["issues"])
    snapshot[tid]["cues"][2]["ActiveLoop"] = 0
    root = ET.fromstring(source_bytes)
    root.find("COLLECTION").append(deepcopy(original))
    uploaded = client.post("/api/v1/write/source-xml", headers=auth(), json={"filename": "duplicate.xml", "xml_text": ET.tostring(root, encoding="unicode")}).json()
    assert preview(client, {**body, "source_id": uploaded["source_id"]})["conflict"] > 0


def test_review_required_and_source_upload_rejects_app_xml_and_entities(existing_job):
    client, _, body, _, _, _, _, _, _ = existing_job
    result = client.post("/api/v1/write/export-xml", headers=auth(), json=body)
    assert result.status_code == 400 and "確認" in result.json()["detail"]
    for payload in ['<DJ_PLAYLISTS><PRODUCT Name="pyrekordbox"/><COLLECTION/></DJ_PLAYLISTS>', '<!DOCTYPE x [<!ENTITY a "hello">]><DJ_PLAYLISTS/>']:
        response = client.post("/api/v1/write/source-xml", headers=auth(), json={"filename": "bad.xml", "xml_text": payload})
        assert response.status_code == 400
    assert client.get("/api/v1/write/source-xml/../../secret", headers=auth()).status_code == 404


def test_multiple_original_tracks_export_together_and_one_conflict_stops_all(existing_job, tmp_path):
    client, repo, body, snapshots, _, _, original, source_bytes, _ = existing_job
    path = tmp_path / "second.wav"
    path.write_bytes(b"second original")
    tid = repo.upsert_track(content_id=new_id(), path=str(path), fmt="WAV")
    run = repo.create_run(track_id=tid, engine_version="existing-test", params={}, fingerprint=new_id(), beat_source="ANLZ", pssi_used=True)
    candidate = repo.add_candidates(run, [{"type": "INTRO_START", "time_ms": 1000, "confidence": 90, "rank": 1}])[0]
    repo.upsert_decision(candidate_id=candidate, accepted=True, cue_kind="MEMORY")
    # Attach a second analyzed track to this test job without touching any source library.
    repo._conn.execute("INSERT INTO job_track(job_id,track_id,status,run_id) VALUES (?,?,?,?)", (body["job_id"], tid, "COMPLETED", run))
    repo._conn.commit()
    second = deepcopy(original)
    second.attrib.update(Name="Second", TrackID="5678", Location=path.as_uri())
    for mark in second.findall("POSITION_MARK"):
        second.remove(mark)
    root = ET.fromstring(source_bytes)
    root.find("COLLECTION").remove(root.findall("COLLECTION/TRACK")[1])
    root.find("COLLECTION").append(second)
    snapshots[tid] = deepcopy(next(iter(snapshots.values())))
    snapshots[tid]["detail"].update(title="Second", path=str(path))
    snapshots[tid]["cues"] = []
    uploaded = client.post("/api/v1/write/source-xml", headers=auth(), json={"filename": "two.xml", "xml_text": ET.tostring(root, encoding="unicode")}).json()
    body = {**body, "source_id": uploaded["source_id"]}
    plan = preview(client, body)
    assert (plan["add"], plan["preserved"], plan["conflict"]) == (6, 3, 0)
    output = client.post("/api/v1/write/export-xml", headers=auth(), json={**body, "confirmation_hash": plan["confirmation_hash"]})
    assert output.status_code == 200
    assert len(ET.parse(output.json()["xml_path"]).getroot().findall("COLLECTION/TRACK")) == 2
    folders_before = set(Path(output.json()["folder"]).parent.iterdir())
    snapshots[tid]["detail"]["title"] = "Changed"
    changed = preview(client, body)
    assert changed["conflict"] > 0
    blocked = client.post("/api/v1/write/export-xml", headers=auth(), json={**body, "confirmation_hash": changed["confirmation_hash"]})
    assert blocked.status_code == 400
    assert set(Path(output.json()["folder"]).parent.iterdir()) == folders_before


def test_stale_metadata_cannot_replace_current_genre_or_key(existing_job):
    client, _, body, snapshots, tid, _, _, _, _ = existing_job
    snapshots[tid]["xml_metadata"] = {"Genre": "Edited genre", "Tonality": "Fm", "Rating": 255}
    plan = preview(client, body)
    assert plan["conflict"] > 0 and any("現在の曲情報" in issue for issue in plan["issues"])


def test_final_cue_uses_actual_duration_without_changing_native_xml_totaltime(existing_job):
    client, repo, body, _, _, _, _, _, run = existing_job
    candidate = repo.add_candidates(run, [{"type": "TRACK_END", "time_ms": 20100, "confidence": 85, "rank": 1}])[0]
    repo.upsert_decision(candidate_id=candidate, accepted=True, cue_kind="MEMORY")
    plan = preview(client, body)
    assert plan["conflict"] == 0
    result = client.post("/api/v1/write/export-xml", headers=auth(), json={**body, "confirmation_hash": plan["confirmation_hash"]})
    assert result.status_code == 200, result.text
    track = ET.parse(result.json()["xml_path"]).getroot().find("COLLECTION/TRACK")
    assert track.get("TotalTime") == "20"
    assert any(float(mark.get("Start")) == 20.1 for mark in track.findall("POSITION_MARK"))
    repo.upsert_decision(candidate_id=candidate, accepted=True, cue_kind="MEMORY", edited_time_ms=20300)
    assert preview(client, body)["conflict"] > 0  # The audio really ends at 20.25 seconds.
