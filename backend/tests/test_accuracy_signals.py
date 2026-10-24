import json
from pathlib import Path
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis import ai
from app.analysis.cue_targets import target_candidates
from app.analysis.features import BeatFeatures, extract_features
from app.analysis.phrases import best_phase_grid
from app.analysis.pipeline import analyze_file
from app.analysis.structure_evidence import boundary_strengths, repeated_section_scores
from app.analysis.vocals import vocal_start_from_stems
from app.common import new_id
from app.config import get_settings
from app.main import app
from app.persistence.repositories import Repository
from helpers import write_wav


def stems(duration=8, start=3):
    count = round(duration * 10)
    vocal = np.zeros(count)
    vocal[round(start * 10):round((start + 1.5) * 10)] = .1
    return {"schema": 1, "model": "htdemucs", "hop_sec": .1, "duration_sec": duration,
            "mix": [.2] * count,
            "stems": {"vocals": vocal.tolist(), "drums": [.03] * count, "bass": [.04] * count, "other": [.02] * count}}


def test_beat_descriptor_hears_harmony_after_an_identical_attack():
    sr = 8000
    t = np.arange(sr // 2) / sr
    attack = .3 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 30)
    tail = (t > .12).astype(float)
    first = attack + tail * .2 * np.sin(2 * np.pi * 261.63 * t)
    second = attack + tail * .2 * np.sin(2 * np.pi * 369.99 * t)
    features = extract_features(np.concatenate((first, second)), sr, np.array([0, .5]))
    assert np.linalg.norm(features.chroma[0] - features.chroma[1]) > .5
    assert np.linalg.norm(features.bands[0] - features.bands[1]) > .2
    assert features.flux[1] > 0


def test_uniform_loop_is_not_evidence_of_a_distinctive_repeated_section():
    beats = 128
    feat = BeatFeatures(np.arange(beats) * .5, np.ones(beats), np.ones(beats), np.zeros(beats), np.zeros(beats),
                        chroma=np.ones((beats, 12)) / 12, bands=np.ones((beats, 16)) / 16)
    assert np.allclose(repeated_section_scores(feat, np.arange(0, beats, 4)), 0)


def test_nonlocal_ordered_passages_supply_repetition_evidence():
    rng = np.random.default_rng(12)
    harmony = rng.dirichlet(np.full(12, .15), size=32)
    harmony[24:28] = harmony[8:12]
    beat_harmony = np.repeat(harmony, 4, axis=0)
    feat = BeatFeatures(np.arange(128) * .5, np.ones(128), np.ones(128) * .3, np.zeros(128), np.zeros(128), chroma=beat_harmony)
    scores = repeated_section_scores(feat, np.arange(0, 128, 4))
    assert scores[8] > .9 and scores[24] > .9


def test_phrase_phase_follows_section_change_instead_of_a_loud_drum_hit():
    harmony = np.zeros((48, 12))
    harmony[:5, 0] = 1
    harmony[5:21, 4] = 1
    harmony[21:37, 7] = 1
    harmony[37:, 0] = 1
    beats = 48 * 4
    onset = np.zeros(beats)
    onset[np.arange(2, 48, 16) * 4] = 100
    feat = BeatFeatures(np.arange(beats) * .5, np.ones(beats), np.ones(beats) * .2, np.zeros(beats), onset,
                        chroma=np.repeat(harmony, 4, axis=0))
    downbeats = np.arange(0, beats, 4)
    grid = best_phase_grid(downbeats, boundary_strengths(feat, downbeats), bars_per_phrase=16)
    assert grid.phase_bars == 5


def test_vocal_onset_requires_sustained_component_and_rejects_weak_bleed():
    data = stems()
    assert vocal_start_from_stems(data) == pytest.approx(3)
    data["stems"]["vocals"] = [.002] * 80
    assert vocal_start_from_stems(data) is None
    data["stems"]["vocals"] = [0] * 80
    data["stems"]["vocals"][10:12] = [.1, .1]
    assert vocal_start_from_stems(data) is None


def test_lrc_keeps_priority_over_separated_vocal_start_and_cache_fingerprint_changes(tmp_path):
    sr = 8000
    t = np.arange(sr * 8) / sr
    path = write_wav(tmp_path / "voice.wav", .2 * np.sin(2 * np.pi * 220 * t), sr)
    first = analyze_file(str(path), bpm=120, cue_targets=["VOCAL_START"], stem_analysis=stems())
    assert first.candidates[0].time_sec == 3
    assert "HTDemucs" in first.candidates[0].evidence[0].detail
    assert first.candidates[0].confidence == 65
    path.with_suffix(".lrc").write_text("[00:01.000]Words", encoding="utf-8")
    second = analyze_file(str(path), bpm=120, cue_targets=["VOCAL_START"], stem_analysis=stems())
    assert second.candidates[0].time_sec == 1 and "LRC" in second.candidates[0].evidence[0].detail
    assert first.fingerprint != second.fingerprint


def test_invalid_stem_results_cannot_be_used_as_valid_cache():
    data = stems()
    ai.validate_stems(data)
    for change in (lambda d: d.update(hop_sec=float("nan")), lambda d: d["mix"].pop(),
                   lambda d: d["stems"]["vocals"].__setitem__(0, -1)):
        data = stems()
        change(data)
        with pytest.raises(ValueError):
            ai.validate_stems(data)


def test_cancellation_stops_inference_process_and_releases_single_inference_lock(tmp_path, monkeypatch):
    audio = tmp_path / "original.wav"
    audio.write_bytes(b"unchanged original")
    cancelled = threading.Event()
    instances = []

    class Process:
        returncode = None

        def __init__(self, *args, **kwargs):
            instances.append(self)
            cancelled.set()

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, **kwargs):
            return self.returncode

    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    with pytest.raises(ai.AnalysisCancelled):
        ai.analyze_stems(str(audio), cancel_event=cancelled)
    assert instances[0].returncode == -15
    assert ai._INFERENCE_LOCK.acquire(blocking=False)
    ai._INFERENCE_LOCK.release()
    assert audio.read_bytes() == b"unchanged original"


def test_inference_cache_follows_audio_contents_and_never_edits_source(tmp_path, monkeypatch):
    audio = tmp_path / "original.wav"
    audio.write_bytes(b"first original")
    calls = []

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            calls.append(args)
            Path(args[args.index("--output") + 1]).write_text(json.dumps(stems()), encoding="utf-8")

        def poll(self):
            return 0

    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    assert ai.analyze_stems(str(audio))[1] is False
    assert ai.analyze_stems(str(audio))[1] is True
    assert len(calls) == 1 and audio.read_bytes() == b"first original"
    audio.write_bytes(b"changed original")
    assert ai.analyze_stems(str(audio))[1] is False and len(calls) == 2


def test_audio_changed_during_inference_is_not_kept_as_a_valid_result(tmp_path, monkeypatch):
    audio = tmp_path / "changing.wav"
    audio.write_bytes(b"before")
    outputs = []

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            output = Path(args[args.index("--output") + 1])
            outputs.append(output)
            output.write_text(json.dumps(stems()), encoding="utf-8")
            audio.write_bytes(b"changed during inference")

        def poll(self):
            return 0

    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    with pytest.raises(ValueError, match="音源が変更"):
        ai.analyze_stems(str(audio))
    assert not outputs[0].exists()


def test_ai_status_is_authenticated_and_unavailable_mode_does_not_create_a_job(monkeypatch):
    monkeypatch.setattr("app.api.routes_jobs.ai_status", lambda: {"available": False, "reason": "missing"})
    headers = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as client:
        assert client.get("/api/v1/analysis/ai-status").status_code == 401
        assert client.get("/api/v1/analysis/ai-status", headers=headers).json()["available"] is False
        before = client.get("/api/v1/jobs", headers=headers).json()
        response = client.post("/api/v1/jobs", headers=headers, json={"params": {"analysis_quality": "AI"}, "tracks": [{"content_id": new_id(), "path": "missing.wav"}]})
        assert response.status_code == 400
        assert client.get("/api/v1/jobs", headers=headers).json() == before


@pytest.mark.parametrize("specialized", [False, True])
def test_ai_job_uses_separated_vocals_without_automatically_adopting_cues(tmp_path, monkeypatch, specialized):
    sr = 8000
    t = np.arange(sr * 8) / sr
    path = write_wav(tmp_path / "track.wav", .2 * np.sin(2 * np.pi * 220 * t), sr)
    original = path.read_bytes()
    monkeypatch.setattr("app.api.routes_jobs.ai_status", lambda: {"available": True})
    monkeypatch.setattr("app.jobs.worker.analyze_stems", lambda *args, **kwargs: (stems(), False))
    headers = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as client:
        params = {"analysis_quality": "AI", "bpm": 120, "cue_targets": ["VOCAL_START"]}
        if specialized:
            params.update(cue_mode="INTRO_OUTRO", intro_outro={"targets": ["VOCAL_START"]})
        response = client.post("/api/v1/jobs", headers=headers, json={"params": params, "tracks": [{"content_id": new_id(), "path": str(path)}]})
        assert response.status_code == 201
        job = response.json()["job_id"]
        for _ in range(100):
            status = client.get(f"/api/v1/jobs/{job}", headers=headers).json()
            if status["status"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(.03)
        assert status["status"] == "COMPLETED" and status["failed"] == 0
        candidates = client.get(f"/api/v1/jobs/{job}/candidates", headers=headers).json()["candidates"]
        assert candidates[0]["time_ms"] == 3000 and candidates[0]["accepted"] is None
        track = client.get(f"/api/v1/jobs/{job}/tracks", headers=headers).json()["tracks"][0]
        assert track["analysis"]["ai_model"] == "htdemucs"
        assert track["analysis"]["vocal_start_sec"] == 3
        if specialized:
            assert track["analysis"]["cue_mode"] == "INTRO_OUTRO" and track["analysis"]["analysis_quality"] == "AI"
    assert path.read_bytes() == original


def test_cancel_during_the_last_track_cannot_be_reported_as_completed(tmp_path, monkeypatch):
    from app.jobs.worker import run_job
    from app.jobs.progress import ProgressHub
    sr = 8000
    path = write_wav(tmp_path / "cancel.wav", np.ones(sr), sr)
    cancel = threading.Event()

    def separate(*args, **kwargs):
        cancel.set()
        raise ai.AnalysisCancelled()

    monkeypatch.setattr("app.jobs.worker.analyze_stems", separate)
    params = {"analysis_quality": "AI", "bpm": 120}
    with Repository(get_settings().db_path) as repo:
        tid = repo.upsert_track(content_id=new_id(), path=str(path), fmt="WAV")
        job = repo.create_job(params=params, track_ids=[tid])
    run_job(get_settings().db_path, ProgressHub(), job, params, cancel)
    with Repository(get_settings().db_path) as repo:
        assert repo.get_job(job)["status"] == "CANCELLED"
        assert repo.list_job_tracks(job)[0]["status"] == "CANCELLED"
        assert repo.list_candidates_for_job(job) == []


def test_rekordbox_grid_changed_during_ai_processing_stops_candidate_generation(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from copy import deepcopy
    from app.jobs.worker import run_job
    from app.jobs.progress import ProgressHub

    sr = 8000
    path = write_wav(tmp_path / "grid.wav", np.ones(sr * 8) * .2, sr)
    snapshot = {"source": "REKORDBOX", "available": True, "bpm": 120,
                "beat_times": [i * .5 for i in range(16)], "downbeat_indices": [0, 4, 8, 12],
                "phrase_boundaries": [], "phrase_sections": [], "warnings": []}
    reads = []

    @contextmanager
    def database(**kwargs):
        yield object()

    def read(*args):
        result = deepcopy(snapshot)
        if reads:
            result["beat_times"] = [t + .1 for t in result["beat_times"]]
        reads.append(result)
        return result

    monkeypatch.setattr("app.jobs.worker.open_rekordbox", database)
    monkeypatch.setattr("app.jobs.worker.load_track_analysis", read)
    monkeypatch.setattr("app.jobs.worker.analyze_stems", lambda *args, **kwargs: (stems(), False))
    params = {"analysis_source": "REKORDBOX", "analysis_quality": "AI", "bpm": 120}
    with Repository(get_settings().db_path) as repo:
        tid = repo.upsert_track(content_id=new_id(), path=str(path), fmt="WAV")
        job = repo.create_job(params=params, track_ids=[tid])
    run_job(get_settings().db_path, ProgressHub(), job, params, threading.Event())
    with Repository(get_settings().db_path) as repo:
        assert repo.get_job(job)["failed"] == 1
        track = repo.list_job_tracks(job)[0]
        assert "グリッド・フレーズ・Cue情報が変わりました" in json.loads(track["analysis_json"])["reason"]
        assert repo.list_candidates_for_job(job) == []
