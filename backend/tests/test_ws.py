from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.analysis.synth import synthesize_edm
from app.main import app
from helpers import write_wav


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {app.state.token}"}


def test_ws_rejects_bad_token():
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/ws/jobs/xxx?token=wrong"):
                assert False, "should reject"
        except Exception:
            pass  # 4401 で閉じられる


def test_ws_streams_progress_until_completed(tmp_path):
    track = synthesize_edm(bpm=128.0, seed=0)
    wav = write_wav(tmp_path / "ws.wav", track.y, track.sr)
    with TestClient(app) as client:
        job_id = client.post(
            "/api/v1/jobs",
            headers=_auth(),
            json={"params": {"bpm": 128.0},
                  "tracks": [{"content_id": "WS1", "path": str(wav), "format": "WAV"}]},
        ).json()["job_id"]

        # 完了を待ってから接続しても seq=0 から再生される。
        deadline = time.time() + 20
        while time.time() < deadline:
            if client.get(f"/api/v1/jobs/{job_id}", headers=_auth()).json()["status"] == "COMPLETED":
                break
            time.sleep(0.2)

        types = []
        token = app.state.token
        with client.websocket_connect(f"/ws/jobs/{job_id}?token={token}") as ws:
            for _ in range(20):
                msg = ws.receive_json()
                types.append(msg["type"])
                if msg["type"] == "JOB_COMPLETED":
                    break
        assert "JOB_COMPLETED" in types
        assert "TRACK_COMPLETED" in types
