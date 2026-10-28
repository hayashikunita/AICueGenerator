from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_repo
from app.api.routes_jobs import router
from app.jobs import manager as manager_module, worker
from app.jobs.manager import JobManager
from app.jobs.progress import ProgressHub
from app.persistence.db import init_db
from app.persistence.repositories import Repository
from app.schemas.jobs import JobParams
from app.config import get_settings
from helpers import write_wav


@pytest.fixture
def library(tmp_path):
    db = tmp_path / "resume.db"
    init_db(db)
    with Repository(db) as repo:
        tracks = []
        for index in range(4):
            audio = .2 * np.sin(2 * np.pi * (220 + index * 20) * np.arange(64000) / 8000)
            path = write_wav(tmp_path / f"{index}.wav", audio, 8000)
            tracks.append(repo.upsert_track(content_id=str(index), path=str(path), fmt="WAV"))
        yield db, repo, tracks


@pytest.mark.parametrize("parallelism", [1, 2])
def test_resume_only_unfinished_tracks_preserves_results_decisions_and_counts(library, monkeypatch, parallelism):
    monkeypatch.setattr(get_settings(), "analysis_parallelism", parallelism)
    db, repo, tracks = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    job = repo.create_job(params=params, track_ids=tracks)
    hub = ProgressHub()
    worker._process_track(repo, hub, job, tracks[0], params)
    original = dict(next(row for row in repo.list_job_tracks(job) if row["track_id"] == tracks[0]))
    candidate = repo.list_candidates_for_job(job)[0]
    repo.upsert_decision(candidate_id=candidate["id"], accepted=True, cue_kind="MEMORY", edited_time_ms=500)
    repo.set_job_track_status(job, tracks[1], "FAILED", "DECODE_FAILED")
    repo.bump_job_counts(job, failed=1)
    repo.set_job_track_status(job, tracks[2], "RUNNING")
    repo.set_job_status(job, "RUNNING")

    process = Mock(wraps=worker._process_track)
    monkeypatch.setattr(worker, "_process_track", process)
    worker.run_job(db, hub, job, params, threading.Event())

    assert {call.args[3] for call in process.call_args_list} == set(tracks[2:])
    assert process.call_count == 2
    summary = repo.get_job(job)
    assert (summary["status"], summary["total"], summary["completed"], summary["failed"]) == ("COMPLETED", 4, 3, 1)
    assert dict(next(row for row in repo.list_job_tracks(job) if row["track_id"] == tracks[0])) == original
    decision = repo.get_candidate(candidate["id"])
    assert decision["accepted"] == 1 and decision["edited_time_ms"] == 500
    # Retrying the worker after completion cannot inflate counts or create cues.
    process.reset_mock()
    worker.run_job(db, hub, job, params, threading.Event())
    process.assert_not_called()
    assert repo.get_job(job)["completed"] == 3


def test_simultaneous_resume_starts_once_and_cancellation_still_works(library, monkeypatch):
    db, repo, tracks = library
    params = JobParams().model_dump()
    job = repo.create_job(params=params, track_ids=tracks)
    repo.set_job_status(job, "RUNNING")
    entered, finished = threading.Event(), threading.Event()

    def blocked_worker(db_path, hub, job_id, saved_params, cancel):
        assert job_id == job and saved_params == params
        entered.set()
        try:
            assert cancel.wait(10)
            with Repository(db_path) as result:
                result.set_job_status(job_id, "CANCELLED")
        finally:
            finished.set()

    run = Mock(side_effect=blocked_worker)
    monkeypatch.setattr(manager_module, "run_job", run)
    manager = JobManager(db)
    try:
        with ThreadPoolExecutor(max_workers=4) as requests:
            results = list(requests.map(lambda _: manager.resume(job), range(4)))
        assert results.count(True) == 1 and results.count(False) == 3
        assert entered.wait(5) and manager.is_active(job)
        assert manager.cancel(job)
        assert finished.wait(5)
        deadline = time.monotonic() + 5
        while manager.is_active(job) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not manager.is_active(job)
        assert not manager.cancel(job)
        run.assert_called_once()
    finally:
        manager.shutdown()


def test_resume_api_detects_interruption_and_enforces_auth_and_status(library, monkeypatch):
    db, repo, tracks = library
    job = repo.create_job(params=JobParams().model_dump(), track_ids=tracks)
    repo.set_job_status(job, "RUNNING")
    release = threading.Event()
    monkeypatch.setattr(manager_module, "run_job", lambda *args: release.wait(10))
    manager = JobManager(db)
    app = FastAPI()
    app.state.manager = manager
    app.state.token = "resume-test"
    app.include_router(router)

    def repository():
        with Repository(db) as result:
            yield result

    app.dependency_overrides[get_repo] = repository
    headers = {"Authorization": "Bearer resume-test"}
    try:
        with TestClient(app) as client:
            assert client.post(f"/api/v1/jobs/{job}/resume").status_code == 401
            assert client.get(f"/api/v1/jobs/{job}", headers=headers).json()["can_resume"] is True
            assert client.get("/api/v1/jobs", headers=headers).json()["jobs"][0]["can_resume"] is True
            assert client.post("/api/v1/jobs/missing/resume", headers=headers).status_code == 404
            assert client.post(f"/api/v1/jobs/{job}/resume", headers=headers).json() == {"resumed": True}
            assert client.get(f"/api/v1/jobs/{job}", headers=headers).json()["can_resume"] is False
            assert client.post(f"/api/v1/jobs/{job}/resume", headers=headers).json() == {"resumed": False}
            completed = repo.create_job(params={}, track_ids=tracks[:1])
            repo.set_job_status(completed, "COMPLETED")
            assert client.post(f"/api/v1/jobs/{completed}/resume", headers=headers).status_code == 409
    finally:
        release.set()
        manager.shutdown()
