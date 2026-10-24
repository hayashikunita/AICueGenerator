from contextlib import contextmanager
from types import SimpleNamespace
import wave

import pytest
from fastapi.testclient import TestClient

from app.api import routes_audio
from app.main import app


@pytest.fixture
def library_audio(tmp_path, monkeypatch):
    audio_path = tmp_path / "試聴する曲.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000)
    content = SimpleNamespace(ID="preview-song", Title="Preview", FolderPath=str(audio_path))
    calls = []
    @contextmanager
    def library(**kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(get_content=lambda **kw: content if kw.get("ID") == content.ID else None)
    monkeypatch.setattr(routes_audio, "open_rekordbox", library)
    return audio_path, calls


def test_preview_is_authenticated_and_does_not_require_analysis_job(library_audio):
    path, calls = library_audio
    original = path.read_bytes()
    base = "/api/v1/rekordbox/tracks/preview-song/audio"
    with TestClient(app) as client:
        assert client.get(base, params={"path": str(path)}).status_code == 401
        assert client.get(base, params={"path": str(path), "token": "wrong"}).status_code == 401
        assert calls == []
        response = client.get(base, params={"path": str(path), "token": app.state.token})
        assert response.status_code == 200 and response.content == original
        assert response.headers["content-type"] == "audio/wav"
        assert response.headers["accept-ranges"] == "bytes"
        assert path.read_bytes() == original
        assert client.get(base, params={"path": str(path) + ".other", "token": app.state.token}).status_code == 409
        assert client.get(base.replace("preview-song", "missing"), params={"path": str(path), "token": app.state.token}).status_code == 404


@pytest.mark.parametrize(("spec", "status", "start", "end"), [
    ("bytes=0-99", 206, 0, 100), ("bytes=100-", 206, 100, None),
    ("bytes=-50", 206, -50, None), ("bytes=0-999999", 206, 0, None),
    ("bytes=nope-4", 416, 0, 0), ("bytes=4-nope", 416, 0, 0),
    ("bytes=-", 416, 0, 0), ("bytes=-0", 416, 0, 0),
    ("bytes=20-4", 416, 0, 0), ("bytes=999999-", 416, 0, 0),
    ("bytes=--4", 416, 0, 0), ("bytes=1", 416, 0, 0),
])
def test_preview_range_supports_seeking_and_rejects_bad_requests(library_audio, spec, status, start, end):
    path, _ = library_audio
    data = path.read_bytes()
    with TestClient(app) as client:
        response = client.get("/api/v1/rekordbox/tracks/preview-song/audio", params={"path": str(path)},
                              headers={"Authorization": f"Bearer {app.state.token}", "Range": spec})
        assert response.status_code == status
        if status == 206:
            assert response.content == data[start:end]
            assert int(response.headers["content-length"]) == len(response.content)
        else:
            assert response.headers["content-range"] == f"bytes */{len(data)}"


def test_missing_preview_audio_is_actionable(library_audio):
    path, _ = library_audio
    path.unlink()
    with TestClient(app) as client:
        response = client.get("/api/v1/rekordbox/tracks/preview-song/audio", params={"path": str(path), "token": app.state.token})
        assert response.status_code == 404
        assert "保存場所" in response.json()["detail"]
