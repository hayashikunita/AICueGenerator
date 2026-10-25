from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from app.analysis import ai
from app.analysis.fingerprint import audio_fingerprint
from app.common import loads, new_id
from app.domain.events import EventType
from app.jobs import worker
from app.jobs.progress import ProgressHub
from app.persistence.db import init_db
from app.persistence.repositories import Repository
from app.schemas.jobs import JobParams
from helpers import write_wav


@pytest.fixture
def library(tmp_path):
    db = tmp_path / "jobs.db"
    init_db(db)
    with Repository(db) as repo:
        tracks = []
        for index in range(7):
            time = np.arange(8 * 8000) / 8000
            audio = .2 * np.sin(2 * np.pi * (220 + index * 20) * time)
            source = write_wav(tmp_path / f"{index}.wav", audio, 8000)
            tracks.append(repo.upsert_track(content_id=new_id(), path=str(source), fmt="WAV"))
        yield repo, db, tracks, ProgressHub()


def run(library, tracks, params):
    repo, db, _, hub = library
    job = repo.create_job(params=params, track_ids=tracks)
    worker.run_job(db, hub, job, params, threading.Event())
    summary = repo.get_job(job)
    assert summary["status"] == "COMPLETED"
    return job, {row["track_id"]: dict(row) for row in repo.list_job_tracks(job)}


def test_adding_three_to_four_only_analyses_new_tracks_and_preserves_results(library, monkeypatch):
    repo, _, tracks, hub = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    analyse = Mock(wraps=worker.analyze_file)
    monkeypatch.setattr(worker, "analyze_file", analyse)
    first, original = run(library, tracks[:4], params)
    assert analyse.call_count == 4
    candidates = repo.list_candidates_for_job(first)
    assert candidates
    chosen = candidates[0]
    repo.upsert_decision(candidate_id=chosen["id"], accepted=True, cue_kind="MEMORY", edited_time_ms=500)
    analyse.reset_mock()

    second, added = run(library, tracks, params)
    assert analyse.call_count == 3
    assert {call.args[0] for call in analyse.call_args_list} == {repo.get_track(t)["path"] for t in tracks[4:]}
    assert (repo.get_job(second)["total"], repo.get_job(second)["completed"], repo.get_job(second)["failed"]) == (7, 7, 0)
    for track in tracks[:4]:
        assert added[track]["run_id"] == original[track]["run_id"]
        metadata = loads(added[track]["analysis_json"])
        assert metadata["cached"] is True
        assert metadata["duration_ms"] == 8000
    assert all(not loads(added[t]["analysis_json"]).get("cached") for t in tracks[4:])
    assert repo.get_candidate(chosen["id"])["accepted"] == 1
    assert repo.get_candidate(chosen["id"])["edited_time_ms"] == 500
    assert {row["id"] for row in candidates} <= {row["id"] for row in repo.list_candidates_for_job(second)}
    events = [event for event in hub.events_since(second, 0) if event.type == EventType.TRACK_COMPLETED]
    assert len(events) == 7 and sum(bool(event.data.get("cached")) for event in events) == 4

    analyse.reset_mock()
    third, reused = run(library, tracks, params)
    analyse.assert_not_called()
    assert repo.get_job(third)["completed"] == 7
    assert all(loads(row["analysis_json"])["cached"] for row in reused.values())


@pytest.mark.parametrize("change", ["audio", "params", "engine", "failed", "lyrics"])
def test_changed_or_incomplete_inputs_are_analysed_again(library, monkeypatch, change):
    repo, _, tracks, _ = library
    track = tracks[0]
    params = JobParams(bpm=120, cue_targets=["VOCAL_START"]).model_dump()
    if change == "failed":
        with monkeypatch.context() as patch:
            patch.setattr(worker, "analyze_file", Mock(side_effect=ValueError("Decode failed")))
            _, original = run(library, [track], params)
        assert original[track]["status"] == "FAILED"
    else:
        _, original = run(library, [track], params)
    source = Path(repo.get_track(track)["path"])
    if change == "audio":
        with source.open("r+b") as stream:
            stream.seek(100)
            stream.write(b"\x00\x00")
    elif change == "params":
        params = {**params, "top_k": 1}
    elif change == "engine":
        monkeypatch.setattr(worker, "ENGINE_VERSION", "future-version")
    elif change == "lyrics":
        source.with_suffix(".lrc").write_text("[00:02.00]New lyrics\n", encoding="utf-8")
    analyse = Mock(wraps=worker.analyze_file)
    monkeypatch.setattr(worker, "analyze_file", analyse)
    _, result = run(library, [track], params)
    analyse.assert_called_once()
    assert result[track]["status"] == "COMPLETED"
    assert result[track]["run_id"] != original[track]["run_id"]
    assert not loads(result[track]["analysis_json"]).get("cached")


@pytest.mark.parametrize("scope,require_end", [("FULL", False), ("VOCAL", False), ("VOCAL", True)])
def test_existing_ai_results_skip_both_ai_and_audio_analysis(library, monkeypatch, scope, require_end):
    repo, _, tracks, _ = library
    track = tracks[0]
    source = Path(repo.get_track(track)["path"])
    targets = ["VOCAL_START", "VOCAL_END"] if require_end else ["VOCAL_START"]
    params = JobParams(bpm=120, cue_mode="INTRO_OUTRO", analysis_quality="AI", ai_scope=scope,
                       intro_outro={"targets": targets}).model_dump()
    stems = {"schema": 1, "model": "htdemucs", "duration_sec": 8, "hop_sec": .1,
             "mix": [.2] * 80, "stems": {name: [.1 if name == "vocals" and 20 <= i < 60 else 0 for i in range(80)]
                                       for name in ("vocals", "drums", "bass", "other")}}
    if scope == "VOCAL":
        stems.update(schema=2, scope="VOCAL", analyzed_sec=8, scan_complete=True, stems={"vocals": stems["stems"]["vocals"]})

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            Path(args[args.index("--output") + 1]).write_text(json.dumps(stems), encoding="utf-8")

        def poll(self):
            return 0

    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    _, original = run(library, [track], params)
    assert original[track]["status"] == "COMPLETED"

    # The previous fingerprint format must remain readable after this update.
    old_fp = audio_fingerprint(source)
    old_fp = "sha256:" + hashlib.sha256(old_fp.encode() + hashlib.sha256(b"none").digest()).hexdigest()
    old_fp = "sha256:" + hashlib.sha256(old_fp.encode() + json.dumps(stems, sort_keys=True).encode()).hexdigest()
    stored_fp = repo._conn.execute("SELECT audio_fingerprint FROM analysis_run WHERE id=?", (original[track]["run_id"],)).fetchone()[0]
    assert stored_fp == old_fp

    separate, analyse = Mock(side_effect=AssertionError("AI must not run again")), Mock(side_effect=AssertionError("Audio must not run again"))
    monkeypatch.setattr(worker, "analyze_stems", separate)
    monkeypatch.setattr(worker, "analyze_file", analyse)
    _, result = run(library, [track], params)
    separate.assert_not_called()
    analyse.assert_not_called()
    assert result[track]["run_id"] == original[track]["run_id"]
    metadata = loads(result[track]["analysis_json"])
    assert metadata["cached"] and metadata["ai_cached"]
    assert "ai_started_at" not in metadata and "ai_progress" not in metadata
