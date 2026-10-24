from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import routes_rekordbox
from app.domain.enums import ErrorCode
from app.main import app
from app.rekordbox.errors import AdapterError
from app.rekordbox.reader import list_playlists, playlist_tracks


def _playlist(id, name, parent=None, folder=False, smart=False):
    return SimpleNamespace(ID=id, Name=name, ParentID=parent, is_folder=folder, is_smart_playlist=smart)


def _track(id, title, artist, bpm=12800, path="C:/Music/track.wav"):
    return SimpleNamespace(ID=id, Title=title, Artist=SimpleNamespace(Name=artist), BPM=bpm, FolderPath=path, Length=180)


class Library:
    def __init__(self):
        self.playlists = [
            _playlist("folder", "DJ sets", folder=True),
            _playlist("set", "週末", "folder"),
            _playlist("other", "週末"),
            _playlist("empty", "Empty"),
            _playlist("smart", "Smart", smart=True),
        ]
        self.tracks = [_track("1", "First Drop", "Artist A"), _track("2", "二曲目", "Artist B", path=None)]
        self.songs = [SimpleNamespace(ID="s2", TrackNo=2, Content=self.tracks[1]), SimpleNamespace(ID="s1", TrackNo=1, Content=self.tracks[0])]

    def get_playlist(self, **kwargs):
        if "ID" in kwargs:
            return next((p for p in self.playlists if p.ID == kwargs["ID"]), None)
        return self.playlists

    def get_playlist_songs(self, *, PlaylistID):
        return self.songs if PlaylistID == "set" else []

    def get_playlist_contents(self, playlist):
        assert playlist.ID == "smart"
        return self.tracks


@pytest.fixture
def library_api(monkeypatch):
    library = Library()

    @contextmanager
    def open_library(**kwargs):
        yield library

    monkeypatch.setattr(routes_rekordbox, "open_rekordbox", open_library)
    with TestClient(app) as client:
        yield client, library


def _auth():
    return {"Authorization": f"Bearer {app.state.token}"}


def test_playlist_hierarchy_distinguishes_duplicate_names():
    by_id = {p["id"]: p for p in list_playlists(Library())}
    assert by_id["set"]["path"] == "DJ sets / 週末"
    assert by_id["other"]["path"] == "週末"
    assert by_id["folder"]["is_folder"] is True
    assert by_id["smart"]["is_smart"] is True


def test_playlist_tracks_keep_registered_order_and_metadata():
    name, tracks = playlist_tracks(Library(), "set")
    assert name == "週末"
    assert [t["content_id"] for t in tracks] == ["1", "2"]
    assert tracks[0]["artist"] == "Artist A" and tracks[0]["bpm"] == 128
    assert tracks[1]["path"] is None
    assert playlist_tracks(Library(), "other")[1] == []


def test_playlist_list_api(library_api):
    client, _ = library_api
    response = client.get("/api/v1/rekordbox/playlists", headers=_auth())
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert len(response.json()["playlists"]) == 5


def test_playlist_pagination_and_search(library_api):
    client, _ = library_api
    endpoint = "/api/v1/rekordbox/playlists/set/tracks"
    first = client.get(endpoint, params={"limit": 1}, headers=_auth()).json()
    assert first["total"] == 2 and first["has_more"] is True
    assert first["playlist_name"] == "週末"
    assert first["tracks"][0]["content_id"] == "1"
    second = client.get(endpoint, params={"limit": 1, "offset": 1}, headers=_auth()).json()
    assert second["tracks"][0]["content_id"] == "2" and second["has_more"] is False
    filtered = client.get(endpoint, params={"query": "FIRST artist a"}, headers=_auth()).json()
    assert filtered["total"] == 1 and filtered["tracks"][0]["title"] == "First Drop"
    missing = client.get(endpoint, params={"query": "absent"}, headers=_auth()).json()
    assert missing["available"] is True and missing["tracks"] == []


def test_empty_and_smart_playlists(library_api):
    client, _ = library_api
    empty = client.get("/api/v1/rekordbox/playlists/empty/tracks", headers=_auth()).json()
    assert empty["available"] is True and empty["total"] == 0
    smart = client.get("/api/v1/rekordbox/playlists/smart/tracks", headers=_auth()).json()
    assert smart["available"] is True and smart["total"] == 2


@pytest.mark.parametrize(("id", "expected"), [("absent", 404), ("folder", 400)])
def test_missing_playlist_and_folder(library_api, id, expected):
    client, _ = library_api
    assert client.get(f"/api/v1/rekordbox/playlists/{id}/tracks", headers=_auth()).status_code == expected


def test_playlist_endpoints_require_auth(library_api):
    client, _ = library_api
    assert client.get("/api/v1/rekordbox/playlists").status_code == 401
    assert client.get("/api/v1/rekordbox/playlists/set/tracks").status_code == 401


@pytest.mark.parametrize("endpoint", ["/playlists", "/playlists/set/tracks"])
def test_playlist_connection_failure_is_reported(library_api, monkeypatch, endpoint):
    client, _ = library_api

    @contextmanager
    def unavailable(**kwargs):
        raise AdapterError(ErrorCode.DB_KEY_UNAVAILABLE, "接続を確認してください")
        yield

    monkeypatch.setattr(routes_rekordbox, "open_rekordbox", unavailable)
    result = client.get("/api/v1/rekordbox" + endpoint, headers=_auth())
    assert result.status_code == 200
    assert result.json()["available"] is False
    assert result.json()["reason"] == "接続を確認してください"


def test_read_failure_is_not_reported_as_empty_playlist(library_api):
    client, library = library_api

    def fail(**kwargs):
        raise RuntimeError("private database error")

    library.get_playlist_songs = fail
    result = client.get("/api/v1/rekordbox/playlists/set/tracks", headers=_auth()).json()
    assert result["available"] is False
    assert "private database error" not in result["reason"]
