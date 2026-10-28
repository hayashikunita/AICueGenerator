from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from app.analysis import ai
from app.config import get_settings
from app.jobs import worker
from app.jobs.progress import ProgressHub
from app.persistence.db import init_db
from app.persistence.repositories import Repository
from app.schemas.jobs import JobParams
from helpers import write_wav


@pytest.fixture
def parallel_library(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "analysis_parallelism", 2)
    monkeypatch.setattr(ai, "_has_parallel_memory", lambda: True)
    db = tmp_path / "parallel.db"
    init_db(db)
    with Repository(db) as repo:
        tracks = []
        for index in range(4):
            audio = .2 * np.sin(2 * np.pi * (220 + index * 20) * np.arange(64000) / 8000)
            path = write_wav(tmp_path / f"{index}.wav", audio, 8000)
            tracks.append(repo.upsert_track(content_id=str(index), path=str(path), fmt="WAV"))
        yield db, repo, tracks


def test_parallel_tracks_overlap_and_publish_each_result_once(parallel_library, monkeypatch):
    db, repo, tracks = parallel_library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    job = repo.create_job(params=params, track_ids=tracks)
    barrier = threading.Barrier(2)
    connections, lock = set(), threading.Lock()
    analyze = worker.analyze_file

    def simultaneous(track_repo, *args, **kwargs):
        with lock:
            connections.add((threading.get_ident(), id(track_repo._conn)))
        return original_process(track_repo, *args, **kwargs)

    def paired_analysis(*args, **kwargs):
        barrier.wait(timeout=10)
        return analyze(*args, **kwargs)

    original_process = worker._process_track
    monkeypatch.setattr(worker, "_process_track", simultaneous)
    monkeypatch.setattr(worker, "analyze_file", paired_analysis)
    hub = ProgressHub()
    worker.run_job(db, hub, job, params, threading.Event())
    summary = repo.get_job(job)
    assert (summary["status"], summary["completed"], summary["failed"]) == ("COMPLETED", 4, 0)
    assert len({thread for thread, _ in connections}) == 2
    rows = repo.list_job_tracks(job)
    assert all(row["status"] == "COMPLETED" for row in rows)
    assert len({row["run_id"] for row in rows}) == 4
    assert len(repo.list_candidates_for_job(job)) == 4
    events = hub.events_since(job, 0)
    assert sum(event.type.value == "TRACK_COMPLETED" for event in events) == 4
    assert events[-1].type.value == "JOB_COMPLETED"


@pytest.mark.parametrize("fail", [False, True])
def test_cancellation_or_worker_failure_stops_both_and_does_not_start_more(parallel_library, monkeypatch, fail):
    db, repo, tracks = parallel_library
    job = repo.create_job(params={}, track_ids=tracks)
    cancel = threading.Event()
    barrier = threading.Barrier(3 if not fail else 2)
    seen, lock = [], threading.Lock()

    def process(track_repo, hub, job_id, track_id, params, *, cancel_event):
        with lock:
            seen.append(track_id)
            first = len(seen) == 1
        track_repo.set_job_track_status(job_id, track_id, "RUNNING")
        barrier.wait(timeout=10)
        if fail and first:
            raise RuntimeError("unexpected worker failure")
        assert cancel_event.wait(10)
        track_repo.set_job_track_status(job_id, track_id, "CANCELLED")

    monkeypatch.setattr(worker, "_process_track", process)
    with ThreadPoolExecutor(max_workers=1) as runner:
        future = runner.submit(worker.run_job, db, ProgressHub(), job, {}, cancel)
        if not fail:
            barrier.wait(timeout=10)
            cancel.set()
        future.result(timeout=15)
    assert len(seen) == 2
    assert repo.get_job(job)["status"] == ("FAILED" if fail else "CANCELLED")
    assert sum(row["status"] == "PENDING" for row in repo.list_job_tracks(job)) == 2


def test_global_inference_limit_and_same_cache_serialization(parallel_library):
    gate = ai._InferenceGate()
    assert gate.acquire(key="same")
    assert not gate.acquire(blocking=False, key="same")
    assert gate.acquire(blocking=False, key="other")
    assert not gate.acquire(blocking=False, key="third")
    gate.release(key="same")
    assert gate.acquire(blocking=False, key="third")
    gate.release(key="other")
    gate.release(key="third")
    with pytest.raises(RuntimeError):
        gate.release()


def test_low_memory_defers_second_separator_but_allows_one_to_progress(parallel_library, monkeypatch):
    gate = ai._InferenceGate()
    monkeypatch.setattr(ai, "_has_parallel_memory", lambda: False)
    assert gate.acquire(blocking=False, key="one")
    assert not gate.acquire(blocking=False, key="two")
    gate.release(key="one")
    assert gate.acquire(blocking=False, key="two")
    gate.release(key="two")


def test_duplicate_parallel_requests_run_one_model_and_reuse_its_cache(parallel_library, tmp_path, monkeypatch):
    audio = tmp_path / "original.wav"
    audio.write_bytes(b"unchanged")
    ready, waiting, release = threading.Event(), threading.Event(), threading.Event()
    stems = {"schema": 1, "model": "htdemucs", "duration_sec": 1, "hop_sec": .1,
             "mix": [.2] * 10, "stems": {name: [.1] * 10 for name in ("vocals", "drums", "bass", "other")}}

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            self.output = Path(args[args.index("--output") + 1])
            assert args[args.index("--threads") + 1] == "3"
            assert kwargs["env"]["OMP_NUM_THREADS"] == "3"
            ready.set()

        def poll(self):
            if not release.is_set():
                return None
            self.output.write_text(json.dumps(stems))
            return 0

    launch = Mock(side_effect=Process)
    monkeypatch.setattr(get_settings(), "ai_threads", 3)
    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", launch)
    monkeypatch.setattr(ai, "_INFERENCE_LOCK", ai._InferenceGate())

    def progress(value):
        if value["phase"] == "WAITING":
            waiting.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ai.analyze_stems, str(audio))
        try:
            assert ready.wait(5)
            second = pool.submit(ai.analyze_stems, str(audio), progress_callback=progress)
            assert waiting.wait(5)
        finally:
            release.set()
        assert first.result(timeout=5)[1] is False
        assert second.result(timeout=5)[1] is True
    launch.assert_called_once()
    assert audio.read_bytes() == b"unchanged"


def test_parallel_startup_preloads_driver_before_requests(parallel_library, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    initialized = []
    monkeypatch.setattr(main, "initialize_rekordbox", lambda: initialized.append(True))

    def metadata(repo):
        assert initialized == [True]

    monkeypatch.setattr(main, "backfill_track_metadata", metadata)
    with TestClient(main.app) as client:
        assert initialized == [True]
        assert client.get("/api/v1/health", headers={"Authorization": f"Bearer {main.app.state.token}"}).status_code == 200
