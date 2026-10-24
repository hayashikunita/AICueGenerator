from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.common import loads
from app.config import get_settings
from app.domain.enums import ErrorCode
from app.main import app
from app.persistence.db import init_db
from app.persistence.repositories import Repository
from app.rekordbox import metadata


TITLE = "Lottery 4.0 (Dirty)"
ARTIST = "Shaggy, Jeremih, Rick Ross, Skillibeng"


def fake_library(monkeypatch, path):
    opened = []
    content = SimpleNamespace(ID="135504988", Title=TITLE, Artist=SimpleNamespace(Name=ARTIST),
                              Album=SimpleNamespace(Name="Lottery 4.0"), FolderPath=str(path))

    @contextmanager
    def open_library(**kwargs):
        opened.append(kwargs)
        yield SimpleNamespace(get_content=lambda **query: content if query["ID"] == content.ID else None)

    monkeypatch.setattr(metadata, "open_rekordbox", open_library)
    return opened


def test_metadata_lookup_checks_both_content_id_and_audio_path(monkeypatch, tmp_path):
    path = tmp_path / "unreadable-86566843.mp3"
    opened = fake_library(monkeypatch, path)
    assert metadata.read_track_metadata([{"content_id": "135504988", "path": str(path)}]) == {
        "135504988": {"title": TITLE, "artist": ARTIST, "album": "Lottery 4.0"},
    }
    assert metadata.read_track_metadata([{"content_id": "135504988", "path": str(tmp_path / "other.mp3")}]) == {}
    assert metadata.read_track_metadata([{"content_id": "file-path", "path": str(path)}]) == {}
    assert len(opened) == 2


def test_offline_library_keeps_filename_fallback_available(monkeypatch, tmp_path):
    @contextmanager
    def unavailable(**kwargs):
        raise metadata.AdapterError(ErrorCode.UNKNOWN_SCHEMA, "test unavailable")
        yield

    monkeypatch.setattr(metadata, "open_rekordbox", unavailable)
    assert metadata.read_track_metadata([{"content_id": "135504988", "path": str(tmp_path / "song.mp3")}]) == {}


def test_cached_metadata_survives_retry_but_does_not_follow_another_file(tmp_path):
    db_path = tmp_path / "app.db"
    init_db(db_path)
    with Repository(db_path) as repo:
        values = {"title": TITLE, "artist": ARTIST}
        track = repo.upsert_track(content_id="135504988", path="song.mp3", fmt="MP3", metadata=values)
        repo.upsert_track(content_id="135504988", path="song.mp3", fmt="MP3")
        assert metadata.track_metadata(repo.get_track(track)) == values
        repo.upsert_track(content_id="135504988", path="other.mp3", fmt="MP3")
        assert metadata.track_metadata(repo.get_track(track)) == {}


def test_legacy_metadata_backfill_changes_only_app_metadata(monkeypatch, tmp_path):
    path = tmp_path / "unreadable-86566843.mp3"
    path.write_bytes(b"original audio")
    opened = fake_library(monkeypatch, path)
    db_path = tmp_path / "app.db"
    init_db(db_path)
    with Repository(db_path) as repo:
        track_id = repo.upsert_track(content_id="135504988", path=str(path), fmt="MP3", duration_ms=192000)
        job = repo.create_job(params={}, track_ids=[track_id])
        run = repo.create_run(track_id=track_id, engine_version="test", params={}, fingerprint="metadata", beat_source="ANLZ", pssi_used=True)
        candidate = repo.add_candidates(run, [{"type": "INTRO_START", "time_ms": 1000, "confidence": 90, "rank": 1}])[0]
        repo.upsert_decision(candidate_id=candidate, accepted=True, cue_kind="MEMORY")
        before = dict(repo.get_track(track_id))
        decisions = [dict(r) for r in repo.list_accepted_decisions_for_job(job)]
        metadata.backfill_track_metadata(repo)
        after = dict(repo.get_track(track_id))
        assert loads(after.pop("metadata_json")) == {"title": TITLE, "artist": ARTIST, "album": "Lottery 4.0"}
        before.pop("metadata_json")
        assert before == after
        assert [dict(r) for r in repo.list_accepted_decisions_for_job(job)] == decisions
        metadata.backfill_track_metadata(repo)
        assert len(opened) == 1
    assert path.read_bytes() == b"original audio"


def test_new_library_job_and_api_keep_original_display_metadata(monkeypatch, tmp_path):
    path = tmp_path / "unreadable-86566843.mp3"
    fake_library(monkeypatch, path)
    monkeypatch.setattr("app.jobs.manager.run_job", lambda *args: None)
    with TestClient(app) as client:
        auth = {"Authorization": f"Bearer {app.state.token}"}
        created = client.post("/api/v1/jobs", headers=auth, json={"tracks": [{"content_id": "135504988", "path": str(path), "format": "MP3"}]})
        assert created.status_code == 201, created.text
        job_id = created.json()["job_id"]
        summary = client.get(f"/api/v1/jobs/{job_id}", headers=auth).json()
        assert (summary["track_title"], summary["track_artist"]) == (TITLE, ARTIST)
        tracks = client.get(f"/api/v1/jobs/{job_id}/tracks", headers=auth).json()["tracks"]
        assert (tracks[0]["title"], tracks[0]["artist"], tracks[0]["album"]) == (TITLE, ARTIST, "Lottery 4.0")
        history = client.get("/api/v1/jobs", headers=auth).json()["jobs"]
        assert next(j for j in history if j["id"] == job_id)["track_title"] == TITLE
        with Repository(get_settings().db_path) as repo:
            repo.set_job_status(job_id, "COMPLETED")
