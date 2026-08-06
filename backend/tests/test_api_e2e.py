from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.analysis.synth import synthesize_edm
from app.main import app
from helpers import write_wav


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {app.state.token}"}


def _wait_job(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/v1/jobs/{job_id}", headers=_auth())
        body = resp.json()
        if body["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return body
        time.sleep(0.2)
    raise AssertionError("job did not finish in time")


def test_full_flow_analyze_decide_plan_execute(tmp_path):
    track = synthesize_edm(bpm=128.0, seed=0)
    wav = write_wav(tmp_path / "song.wav", track.y, track.sr)

    with TestClient(app) as client:
        # 1) ジョブ作成
        resp = client.post(
            "/api/v1/jobs",
            headers=_auth(),
            json={
                "params": {"bpm": 128.0},
                "tracks": [{"content_id": "E2E1", "path": str(wav), "format": "WAV"}],
            },
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # 2) 完了まで待つ
        job = _wait_job(client, job_id)
        assert job["status"] == "COMPLETED"
        assert job["completed"] == 1 and job["failed"] == 0

        # 3) 候補取得（Drop が high 帯で存在）
        resp = client.get(f"/api/v1/jobs/{job_id}/candidates", headers=_auth())
        cands = resp.json()["candidates"]
        drops = [c for c in cands if c["type"] == "DROP"]
        assert drops
        assert any(c["band"] == "high" for c in drops)

        # 4) Drop を承認
        cand_id = drops[0]["id"]
        resp = client.post(
            f"/api/v1/candidates/{cand_id}/decision",
            headers=_auth(),
            json={"accepted": True, "cue_kind": "MEMORY"},
        )
        assert resp.status_code == 200

        # 5) 書込計画（ADD 1件）
        resp = client.post("/api/v1/write/plan", headers=_auth(), json={"job_id": job_id})
        assert resp.status_code == 200
        plan = resp.json()
        assert plan["add"] == 1
        plan_id = plan["plan_id"]
        chash = plan["confirmation_hash"]

        # 6) 実行（P0前・rekordbox 稼働のためフェイルクローズで拒否）
        resp = client.post(
            "/api/v1/write/execute",
            headers=_auth(),
            json={"plan_id": plan_id, "confirmation_hash": chash},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error_code"] == "WRITE_DISABLED"


def test_job_missing_audio_marks_failed(tmp_path):
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/jobs",
            headers=_auth(),
            json={"tracks": [{"content_id": "MISS1", "path": str(tmp_path / "nope.wav")}]},
        )
        job_id = resp.json()["job_id"]
        job = _wait_job(client, job_id)
        assert job["status"] == "COMPLETED"
        assert job["failed"] == 1


def test_diagnostics_endpoint():
    with TestClient(app) as client:
        resp = client.get("/api/v1/diagnostics", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "ok"
        assert "writable" in body


def test_execute_rejects_tampered_hash(tmp_path):
    track = synthesize_edm(bpm=128.0, seed=2)
    wav = write_wav(tmp_path / "s2.wav", track.y, track.sr)
    with TestClient(app) as client:
        job_id = client.post(
            "/api/v1/jobs",
            headers=_auth(),
            json={"params": {"bpm": 128.0},
                  "tracks": [{"content_id": "E2E2", "path": str(wav), "format": "WAV"}]},
        ).json()["job_id"]
        _wait_job(client, job_id)
        cands = client.get(f"/api/v1/jobs/{job_id}/candidates", headers=_auth()).json()["candidates"]
        client.post(f"/api/v1/candidates/{cands[0]['id']}/decision", headers=_auth(),
                    json={"accepted": True, "cue_kind": "MEMORY"})
        plan = client.post("/api/v1/write/plan", headers=_auth(), json={"job_id": job_id}).json()
        resp = client.post("/api/v1/write/execute", headers=_auth(),
                           json={"plan_id": plan["plan_id"], "confirmation_hash": "sha256:tampered"})
        assert resp.json()["error_code"] == "PLAN_HASH_MISMATCH"
