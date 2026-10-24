import json
import threading
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
import pytest

from app.analysis import ai
from app.analysis.ai_progress import inference_progress
from app.common import new_id
from app.main import app
from helpers import write_wav


@pytest.mark.parametrize("log,percent,elapsed,remaining,phase", [
    ("\r 34%|#### | 152.1/444.6 [01:43<03:17, 1.48seconds/s]\r", 34, 103, 197, "SEPARATING"),
    ("0%| | 0/100 [00:00<?, ?seconds/s]\n", 0, 0, None, "SEPARATING"),
    ("100%|####| 100/100 [1:02:03<00:00, 1seconds/s]", 100, 3723, 0, "FINALIZING"),
    ("\r 5%|#| 5/100 [00:04<01:16, 1seconds/s]\r 10%|#| 10/100 [00:08<01:12, 1seconds/s]", 10, 8, 72, "SEPARATING"),
    ("Loading model", None, 0, None, "PREPARING"),
    ("200%|#| 5/100 [00:04<01:16, 1seconds/s]", None, 0, None, "PREPARING"),
])
def test_actual_inference_progress_parses_log_updates(tmp_path, log, percent, elapsed, remaining, phase):
    path = tmp_path / "progress.log"
    path.write_text(log, encoding="utf-8")
    result = inference_progress(path)
    assert result == {"percent": percent, "elapsed_sec": elapsed, "remaining_sec": remaining, "phase": phase}


def test_preparation_elapsed_is_kept_and_missing_log_is_not_reported_as_zero_percent(tmp_path):
    assert inference_progress(tmp_path / "missing.log", elapsed_sec=12.4) == {
        "phase": "PREPARING", "percent": None, "elapsed_sec": 12, "remaining_sec": None}
    path = tmp_path / "progress.log"
    path.write_text("\r10%|#| 10/100 [00:08<01:12, 1seconds/s]", encoding="utf-8")
    assert inference_progress(path, elapsed_sec=15)["elapsed_sec"] == 15


def stem_result():
    return {"schema": 1, "model": "htdemucs", "duration_sec": 8, "hop_sec": .1,
            "mix": [.2] * 80, "stems": {name: [.1 if name == "vocals" and 30 <= i < 50 else 0 for i in range(80)]
                                    for name in ("vocals", "drums", "bass", "other")}}


def test_bridge_publishes_real_inference_updates_and_cached_state(tmp_path, monkeypatch):
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"original")
    updates = []

    class Process:
        returncode = 0

        def __init__(self, args, stdout, **kwargs):
            self.output = Path(args[args.index("--output") + 1])
            self.calls = 0
            stdout.write("\r34%|#| 34/100 [00:10<00:20, 1seconds/s]\r")
            stdout.flush()

        def poll(self):
            self.calls += 1
            if self.calls < 2:
                return None
            self.output.write_text(json.dumps(stem_result()), encoding="utf-8")
            return 0

    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    monkeypatch.setattr(ai.time, "sleep", lambda value: None)
    assert ai.analyze_stems(str(audio), progress_callback=updates.append)[1] is False
    assert any(p["percent"] == 34 and p["remaining_sec"] == 20 for p in updates)
    assert updates[-1]["percent"] == 100
    assert ai.analyze_stems(str(audio), progress_callback=updates.append)[1] is True
    assert updates[-1]["phase"] == "CACHED"
    assert audio.read_bytes() == b"original"


def test_waiting_for_separator_is_visible_and_cancellable(tmp_path, monkeypatch):
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"original")
    cancelled = threading.Event()
    updates = []
    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})

    def waiting(progress):
        updates.append(progress)
        cancelled.set()

    ai._INFERENCE_LOCK.acquire()
    try:
        with pytest.raises(ai.AnalysisCancelled):
            ai.analyze_stems(str(audio), cancel_event=cancelled, progress_callback=waiting)
    finally:
        ai._INFERENCE_LOCK.release()
    assert updates[0]["phase"] == "WAITING" and updates[0]["percent"] is None


def test_running_track_exposes_progress_without_waiting_for_track_completion(tmp_path, monkeypatch):
    source = write_wav(tmp_path / "voice.wav", np.ones(8 * 8000) * .2, 8000)
    ready, release = threading.Event(), threading.Event()

    def separate(*args, progress_callback, **kwargs):
        progress_callback({"phase": "SEPARATING", "percent": 34, "elapsed_sec": 10, "remaining_sec": 20})
        ready.set()
        assert release.wait(8)
        return stem_result(), False

    monkeypatch.setattr("app.api.routes_jobs.ai_status", lambda: {"available": True})
    monkeypatch.setattr("app.jobs.worker.analyze_stems", separate)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", headers=headers, json={"params": {
            "cue_mode": "INTRO_OUTRO", "analysis_quality": "AI", "bpm": 120, "intro_outro": {"targets": ["VOCAL_START"]}},
            "tracks": [{"content_id": new_id(), "path": str(source)}]})
        assert response.status_code == 201
        job = response.json()["job_id"]
        try:
            assert ready.wait(5)
            detail = client.get(f"/api/v1/jobs/{job}", headers=headers).json()
            track = client.get(f"/api/v1/jobs/{job}/tracks", headers=headers).json()["tracks"][0]
            assert detail["completed"] == 0 and track["status"] == "RUNNING"
            assert track["analysis"]["ai_progress"]["percent"] == 34
            assert track["analysis"]["ai_started_at"]
        finally:
            release.set()
        for _ in range(100):
            if client.get(f"/api/v1/jobs/{job}", headers=headers).json()["status"] == "COMPLETED":
                break
            time.sleep(.03)
