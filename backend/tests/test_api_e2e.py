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


def test_export_xml_creates_dated_library(tmp_path):
    import os
    import xml.etree.ElementTree as ET

    from app.config import get_settings

    track = synthesize_edm(bpm=128.0, seed=0)
    wav = write_wav(tmp_path / "export_song.wav", track.y, track.sr)
    with TestClient(app) as client:
        job_id = client.post(
            "/api/v1/jobs",
            headers=_auth(),
            json={
                "params": {"bpm": 128.0},
                "tracks": [{"content_id": "EXP1", "path": str(wav), "format": "WAV"}],
            },
        ).json()["job_id"]
        _wait_job(client, job_id)
        cands = client.get(f"/api/v1/jobs/{job_id}/candidates", headers=_auth()).json()[
            "candidates"
        ]
        drops = [c for c in cands if c["type"] == "DROP"]
        assert drops
        client.post(
            f"/api/v1/candidates/{drops[0]['id']}/decision",
            headers=_auth(),
            json={"accepted": True, "cue_kind": "HOT", "slot": "A"},
        )

        resp = client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["tracks"] == 1
        assert body["cues"] == 1
        assert body["copied"] == 1

        folder = body["folder"]
        # ライブラリは export_dir/yyyymmdd 配下に作られる。
        assert folder.startswith(str(get_settings().export_dir))
        assert os.path.basename(folder).isdigit() and len(os.path.basename(folder)) == 8
        # 音源が複製されている。
        assert os.path.isfile(os.path.join(folder, "export_song.wav"))
        # rekordbox.xml に POSITION_MARK が含まれる。
        tree = ET.parse(body["xml_path"])
        marks = tree.getroot().findall(".//POSITION_MARK")
        assert len(marks) == 1
        assert marks[0].get("Num") == "0"  # HOT slot A -> 0


def test_export_xml_rejects_without_accepted_cues(tmp_path):
    track = synthesize_edm(bpm=128.0, seed=0)
    wav = write_wav(tmp_path / "empty_song.wav", track.y, track.sr)
    with TestClient(app) as client:
        job_id = client.post(
            "/api/v1/jobs",
            headers=_auth(),
            json={
                "params": {"bpm": 128.0},
                "tracks": [{"content_id": "EXP2", "path": str(wav), "format": "WAV"}],
            },
        ).json()["job_id"]
        _wait_job(client, job_id)
        resp = client.post("/api/v1/write/export-xml", headers=_auth(), json={"job_id": job_id})
        assert resp.status_code == 400


def test_top_k_is_honored(tmp_path):
    track = synthesize_edm(bpm=128.0, seed=0)
    wav = write_wav(tmp_path / "topk.wav", track.y, track.sr)
    with TestClient(app) as client:
        job_id = client.post(
            "/api/v1/jobs",
            headers=_auth(),
            json={
                "params": {"bpm": 128.0, "top_k": 1},
                "tracks": [{"content_id": "TOPK1", "path": str(wav), "format": "WAV"}],
            },
        ).json()["job_id"]
        _wait_job(client, job_id)
        cands = client.get(f"/api/v1/jobs/{job_id}/candidates", headers=_auth()).json()[
            "candidates"
        ]
        per_type: dict[str, int] = {}
        for c in cands:
            per_type[c["type"]] = per_type.get(c["type"], 0) + 1
        # top_k=1 なら種別ごとに最大1件。反映されていなければ既定3で超過する。
        assert per_type and all(n <= 1 for n in per_type.values())


def test_rekordbox_search_is_failsafe():
    with TestClient(app) as client:
        resp = client.get("/api/v1/rekordbox/tracks?query=test", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert "available" in body
        assert "tracks" in body


def test_reanalyze_same_track_reuses_cache(tmp_path):
    track = synthesize_edm(bpm=128.0, seed=0)
    wav = write_wav(tmp_path / "cache.wav", track.y, track.sr)
    payload = {
        "params": {"bpm": 128.0},
        "tracks": [{"content_id": "CACHE1", "path": str(wav), "format": "WAV"}],
    }
    with TestClient(app) as client:
        first = client.post("/api/v1/jobs", headers=_auth(), json=payload).json()["job_id"]
        job1 = _wait_job(client, first)
        assert job1["status"] == "COMPLETED"
        cands1 = client.get(f"/api/v1/jobs/{first}/candidates", headers=_auth()).json()["candidates"]

        # 同一 content_id・同一音源・同一パラメータでの再解析はキャッシュ再利用され失敗しない
        second = client.post("/api/v1/jobs", headers=_auth(), json=payload).json()["job_id"]
        job2 = _wait_job(client, second)
        assert job2["status"] == "COMPLETED"
        assert job2["completed"] == 1 and job2["failed"] == 0
        cands2 = client.get(f"/api/v1/jobs/{second}/candidates", headers=_auth()).json()["candidates"]
        assert len(cands2) == len(cands1)


def test_audio_streaming_serves_registered_track(tmp_path):
    track = synthesize_edm(bpm=128.0, seed=0)
    wav = write_wav(tmp_path / "audio.wav", track.y, track.sr)
    payload = {
        "params": {"bpm": 128.0},
        "tracks": [{"content_id": "AUDIO1", "path": str(wav), "format": "WAV"}],
    }
    with TestClient(app) as client:
        job_id = client.post("/api/v1/jobs", headers=_auth(), json=payload).json()["job_id"]
        _wait_job(client, job_id)

        # トラック一覧にパスと track_id が含まれる
        tracks = client.get(f"/api/v1/jobs/{job_id}/tracks", headers=_auth()).json()["tracks"]
        assert len(tracks) == 1
        track_id = tracks[0]["id"]
        assert tracks[0]["path"] == str(wav)

        url = f"/api/v1/tracks/{track_id}/audio"
        # クエリトークンで全体取得できる
        full = client.get(f"{url}?token={app.state.token}")
        assert full.status_code == 200
        assert full.headers["accept-ranges"] == "bytes"

        # Range 指定は 206 と Content-Range を返す
        ranged = client.get(
            f"{url}?token={app.state.token}", headers={"Range": "bytes=0-99"}
        )
        assert ranged.status_code == 206
        assert ranged.headers["content-range"].startswith("bytes 0-99/")
        assert len(ranged.content) == 100

        # トークン無し/誤りは 401
        assert client.get(url).status_code == 401
        assert client.get(f"{url}?token=WRONG").status_code == 401

        # 未登録 track_id は 404
        assert client.get(
            f"/api/v1/tracks/does-not-exist/audio?token={app.state.token}"
        ).status_code == 404


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
