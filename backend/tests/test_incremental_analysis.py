from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from app.analysis import ai, fingerprint, pipeline, reuse
from app.analysis.fingerprint import audio_fingerprint
from app.analysis.reuse import preview_job
from app.common import ENGINE_VERSION, loads, new_id
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


def preview_inputs(repo, tracks):
    return [{"content_id": row["content_id"], "path": row["path"]} for row in (repo.get_track(t) for t in tracks)]


def test_preview_four_saved_three_new_is_read_only_and_matches_worker(library, monkeypatch):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    run(library, tracks[:4], params)
    before = repo._conn.total_changes
    with monkeypatch.context() as patch:
        patch.setattr(worker, "analyze_file", Mock(side_effect=AssertionError("Preview must not analyse")))
        patch.setattr(ai, "analyze_stems", Mock(side_effect=AssertionError("Preview must not run AI")))
        preview = preview_job(repo, preview_inputs(repo, tracks), params)
    assert (preview["total"], preview["cached"], preview["new"], preview["unavailable"]) == (7, 4, 3, 0)
    assert [row["state"] for row in preview["tracks"]] == ["CACHED"] * 4 + ["NEW"] * 3
    assert repo._conn.total_changes == before
    _, result = run(library, tracks, params)
    assert sum(bool(loads(row["analysis_json"]).get("cached")) for row in result.values()) == preview["cached"]
    assert preview_job(repo, preview_inputs(repo, tracks), params)["new"] == 0


@pytest.mark.parametrize("change", ["audio", "lyrics", "params", "colors", "missing"])
def test_preview_validates_reusable_inputs(library, change):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["VOCAL_START"]).model_dump()
    run(library, tracks[:1], params)
    source = Path(repo.get_track(tracks[0])["path"])
    if change == "audio":
        with source.open("r+b") as stream:
            stream.seek(100)
            stream.write(b"\x00\x00")
    elif change == "lyrics":
        source.with_suffix(".lrc").write_text("[00:02.00]New lyrics\n", encoding="utf-8")
    elif change == "params":
        params = {**params, "top_k": 1}
    elif change == "colors":
        params = {**params, "cue_default": {"cue_kind": "HOT", "hot_color": "#0000ff", "memory_color": None}}
    else:
        source.unlink()
    preview = preview_job(repo, preview_inputs(repo, tracks[:2]), params)
    assert preview["tracks"][0]["state"] == ("CACHED" if change == "colors" else "UNAVAILABLE" if change == "missing" else "NEW")
    assert preview["tracks"][1]["state"] == "NEW"


def test_preview_new_tracks_and_new_settings_do_not_hash_audio(library, monkeypatch):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    run(library, tracks[:1], params)
    monkeypatch.setattr(fingerprint.AudioInput, "read", Mock(side_effect=AssertionError("Unnecessary hash")))
    result = preview_job(repo, preview_inputs(repo, tracks), {**params, "top_k": 1})
    assert result["new"] == 7 and result["unavailable"] == 0


def test_preview_rekordbox_snapshot_matches_worker_and_opens_library_once(library, monkeypatch):
    repo, _, tracks, _ = library
    snapshot = {"available": True, "source": "REKORDBOX", "bpm": 120,
                "beat_times": [i * .5 for i in range(16)], "downbeat_indices": [0, 4, 8, 12],
                "phrase_boundaries": [], "phrase_sections": []}
    open_db = Mock(side_effect=lambda **kwargs: nullcontext(object()))
    for module in (worker, reuse):
        monkeypatch.setattr(module, "open_rekordbox", open_db)
        monkeypatch.setattr(module, "load_track_analysis", lambda *args: deepcopy(snapshot))
    params = JobParams(analysis_source="REKORDBOX", cue_targets=["INTRO_START"]).model_dump()
    run(library, tracks[:4], params)
    open_db.reset_mock()
    preview = preview_job(repo, preview_inputs(repo, tracks), params)
    assert (preview["cached"], preview["new"]) == (4, 3)
    open_db.assert_called_once()
    snapshot["beat_times"] = [beat + .01 for beat in snapshot["beat_times"]]
    preview = preview_job(repo, preview_inputs(repo, tracks), params)
    assert preview["new"] == 7 and preview["cached"] == 0


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
    monkeypatch.setattr(ai, "get_settings", lambda: SimpleNamespace(data_dir=library[1].parent, ai_python=None,
                                                                 analysis_parallelism=1, ai_threads=4))
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    hash_audio = Mock(wraps=fingerprint.audio_fingerprint)
    monkeypatch.setattr(fingerprint, "audio_fingerprint", hash_audio)
    monkeypatch.setattr(ai, "audio_fingerprint", hash_audio)
    _, original = run(library, [track], params)
    assert original[track]["status"] == "COMPLETED"
    assert hash_audio.call_count == 2  # Initial input plus the required post-inference check.

    # The previous fingerprint format must remain readable after this update.
    old_fp = audio_fingerprint(source)
    old_fp = "sha256:" + hashlib.sha256(old_fp.encode() + hashlib.sha256(b"none").digest()).hexdigest()
    old_fp = "sha256:" + hashlib.sha256(old_fp.encode() + json.dumps(stems, sort_keys=True).encode()).hexdigest()
    stored_fp = repo._conn.execute("SELECT audio_fingerprint FROM analysis_run WHERE id=?", (original[track]["run_id"],)).fetchone()[0]
    assert stored_fp == old_fp

    separate, analyse = Mock(side_effect=AssertionError("AI must not run again")), Mock(side_effect=AssertionError("Audio must not run again"))
    monkeypatch.setattr(worker, "analyze_stems", separate)
    monkeypatch.setattr(worker, "analyze_file", analyse)
    assert preview_job(repo, preview_inputs(repo, [track]), params)["cached"] == 1
    with monkeypatch.context() as patch:
        patch.setattr(reuse, "load_cached_stems", lambda *args, **kwargs: None)
        assert preview_job(repo, preview_inputs(repo, [track]), params)["new"] == 1
    hash_audio.reset_mock()
    _, result = run(library, [track], params)
    separate.assert_not_called()
    analyse.assert_not_called()
    hash_audio.assert_called_once()
    assert result[track]["run_id"] == original[track]["run_id"]
    metadata = loads(result[track]["analysis_json"])
    assert metadata["cached"] and metadata["ai_cached"]
    assert "ai_started_at" not in metadata and "ai_progress" not in metadata


def test_manual_additions_follow_added_tracks_without_changing_other_history(library, monkeypatch):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    first, original = run(library, tracks[:4], params)
    untouched, _ = run(library, tracks[:4], params)
    candidate = repo.list_candidates_for_run(original[tracks[0]]["run_id"])[0]
    repo.upsert_decision(candidate_id=candidate["id"], accepted=True, cue_kind="MEMORY",
                         edited_time_ms=500, comment="Keep original adjustment")
    previous = [dict(c) for c in repo.list_candidates_for_job(untouched)]
    for time_ms in (1000, 2000):
        manual_id = repo.add_manual_candidate(first, tracks[0], {
            "type": "VOCAL_START", "time_ms": time_ms, "beat": time_ms // 500, "evidence": [],
        })
    latest_run = repo.get_candidate(manual_id)["run_id"]
    repo.upsert_decision(candidate_id=manual_id, accepted=True, cue_kind="HOT", edited_time_ms=2500,
                         slot="B", color="#9900ff", comment="Manual cue")
    analyse = Mock(wraps=worker.analyze_file)
    monkeypatch.setattr(worker, "analyze_file", analyse)

    second, added = run(library, tracks, params)
    assert analyse.call_count == 3
    assert added[tracks[0]]["run_id"] == latest_run
    candidates = repo.list_candidates_for_job(second)
    assert len(candidates) == 9
    assert {c["time_ms"] for c in candidates if c["type"] == "VOCAL_START"} == {1000, 2000}
    copied = next(c for c in candidates if c["type"] == "INTRO_START" and c["track_id"] == tracks[0])
    assert copied["accepted"] and copied["edited_time_ms"] == 500
    manual = repo.get_candidate(manual_id)
    assert (manual["accepted"], manual["edited_time_ms"], manual["cue_kind"], manual["slot"], manual["color"], manual["comment"]) == (1, 2500, "HOT", "B", "#9900ff", "Manual cue")
    assert [dict(c) for c in repo.list_candidates_for_job(untouched)] == previous

    analyse.reset_mock()
    repeated, _ = run(library, tracks, params)
    analyse.assert_not_called()
    assert {c["id"] for c in repo.list_candidates_for_job(repeated)} == {c["id"] for c in candidates}


@pytest.mark.parametrize("change", ["audio", "params"])
def test_manual_results_are_not_reused_for_changed_inputs(library, monkeypatch, change):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    first, _ = run(library, tracks[:1], params)
    manual_id = repo.add_manual_candidate(first, tracks[0], {
        "type": "VOCAL_START", "time_ms": 1000, "beat": 2, "evidence": [],
    })
    if change == "params":
        params = {**params, "top_k": 1}
    else:
        source = Path(repo.get_track(tracks[0])["path"])
        with source.open("r+b") as stream:
            stream.seek(100)
            stream.write(b"\x00\x00")
    analyse = Mock(wraps=worker.analyze_file)
    monkeypatch.setattr(worker, "analyze_file", analyse)
    second, _ = run(library, tracks[:1], params)
    analyse.assert_called_once()
    assert all(c["type"] != "VOCAL_START" for c in repo.list_candidates_for_job(second))
    assert repo.get_candidate(manual_id) is not None


@pytest.mark.parametrize("status", ["RUNNING", "FAILED", "CANCELLED"])
@pytest.mark.parametrize("stage", ["run", "features", "candidates"])
def test_retry_replaces_only_unfinished_partial_results(library, status, stage):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    preserved, _ = run(library, tracks[1:2], params)
    previous = [dict(c) for c in repo.list_candidates_for_job(preserved)]
    partial_run = repo.create_run(
        track_id=tracks[0], engine_version=ENGINE_VERSION, params=params,
        fingerprint=audio_fingerprint(repo.get_track(tracks[0])["path"]), beat_source="MANUAL", pssi_used=False,
    )
    if stage != "run":
        repo.save_feature_summary(partial_run, bpm=1, beat_times=[0, 10], downbeats=[0])
    if stage == "candidates":
        repo.add_candidates(partial_run, [{"type": "DROP", "time_ms": 7000, "confidence": 85, "rank": 1}])
    if status != "RUNNING":
        repo.finish_run(partial_run, status=status, error_id="COMMIT_FAILED")

    job, result = run(library, tracks[:1], params)
    assert (repo.get_job(job)["completed"], repo.get_job(job)["failed"]) == (1, 0)
    assert result[tracks[0]]["run_id"] == partial_run
    assert result[tracks[0]]["status"] == "COMPLETED"
    assert not loads(result[tracks[0]]["analysis_json"]).get("cached")
    assert repo.get_feature_summary(partial_run)["bpm"] == 120
    assert [c["type"] for c in repo.list_candidates_for_job(job)] == ["INTRO_START"]
    saved = repo._conn.execute("SELECT status, error_id FROM analysis_run WHERE id=?", (partial_run,)).fetchone()
    assert tuple(saved) == ("COMPLETED", None)
    assert [dict(c) for c in repo.list_candidates_for_job(preserved)] == previous


@pytest.mark.parametrize("partial_exists", [False, True])
def test_failed_save_rolls_back_and_continues_batch_then_can_retry(library, monkeypatch, partial_exists):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    partial_run = None
    if partial_exists:
        partial_run = repo.create_run(
            track_id=tracks[0], engine_version=ENGINE_VERSION, params=params,
            fingerprint=audio_fingerprint(repo.get_track(tracks[0])["path"]), beat_source="MANUAL", pssi_used=False,
        )
        repo.save_feature_summary(partial_run, bpm=1, beat_times=[0, 10], downbeats=[0])
        repo.add_candidates(partial_run, [{"type": "DROP", "time_ms": 7000, "confidence": 85, "rank": 1}])
        previous = [dict(c) for c in repo.list_candidates_for_run(partial_run)]
    insert = Repository._insert_candidates

    def fail_after_insert(self, run_id, candidates):
        inserted = insert(self, run_id, candidates)
        owner = self._conn.execute("SELECT track_id FROM analysis_run WHERE id=?", (run_id,)).fetchone()[0]
        if owner == tracks[0]:
            raise sqlite3.OperationalError("Simulated interrupted save")
        return inserted

    with monkeypatch.context() as patch:
        patch.setattr(Repository, "_insert_candidates", fail_after_insert)
        job, result = run(library, tracks[:2], params)
    assert (repo.get_job(job)["completed"], repo.get_job(job)["failed"]) == (1, 1)
    assert result[tracks[0]]["status"] == "FAILED"
    assert result[tracks[0]]["error_id"] == "COMMIT_FAILED"
    assert result[tracks[0]]["run_id"] is None
    assert result[tracks[1]]["status"] == "COMPLETED"
    successful_run = result[tracks[1]]["run_id"]
    if partial_exists:
        assert [dict(c) for c in repo.list_candidates_for_run(partial_run)] == previous
        assert repo.get_feature_summary(partial_run)["bpm"] == 1
    else:
        assert repo._conn.execute("SELECT COUNT(*) FROM analysis_run WHERE track_id=?", (tracks[0],)).fetchone()[0] == 0

    retried, result = run(library, tracks[:2], params)
    assert (repo.get_job(retried)["completed"], repo.get_job(retried)["failed"]) == (2, 0)
    assert result[tracks[1]]["run_id"] == successful_run
    assert len(repo.list_candidates_for_job(retried)) == 2


def test_simultaneous_jobs_publish_one_complete_result(library, monkeypatch):
    repo, db, tracks, hub = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    barrier = threading.Barrier(2)
    analyse = worker.analyze_file

    def simultaneous(*args, **kwargs):
        result = analyse(*args, **kwargs)
        barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(worker, "analyze_file", simultaneous)
    jobs = [repo.create_job(params=params, track_ids=tracks[:1]) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker.run_job, db, hub, job, params, threading.Event()) for job in jobs]
        for future in futures:
            future.result(timeout=25)
    rows = [repo.list_job_tracks(job)[0] for job in jobs]
    assert all(repo.get_job(job)["status"] == "COMPLETED" and repo.get_job(job)["failed"] == 0 for job in jobs)
    assert all(row["status"] == "COMPLETED" for row in rows)
    assert rows[0]["run_id"] == rows[1]["run_id"]
    assert sum(bool(loads(row["analysis_json"]).get("cached")) for row in rows) == 1
    assert len(repo.list_candidates_for_run(rows[0]["run_id"])) == 1


@pytest.mark.parametrize("change", ["default_color", "target_color", "cue_kind"])
def test_output_settings_reuse_analysis_and_keep_old_decisions_independent(library, monkeypatch, change):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"],
                       cue_default={"cue_kind": "MEMORY", "memory_color": "#00ffff", "hot_color": "#ff0000"}).model_dump()
    first, _ = run(library, tracks[:1], params)
    repo.add_manual_candidate(first, tracks[0], {"type": "VOCAL_START", "time_ms": 1000, "beat": 2, "evidence": []})
    chosen = next(c for c in repo.list_candidates_for_job(first) if c["type"] == "INTRO_START")
    repo.upsert_decision(candidate_id=chosen["id"], accepted=True, cue_kind="MEMORY", edited_time_ms=500)
    previous = [dict(c) for c in repo.list_candidates_for_job(first)]
    changed = {**params}
    if change == "target_color":
        changed["cue_settings"] = {"INTRO_START": {**params["cue_default"], "memory_color": "#9900ff"}}
    else:
        changed["cue_default"] = {**params["cue_default"], **({"cue_kind": "HOT"} if change == "cue_kind" else {"memory_color": "#9900ff"})}
    analyse = Mock(side_effect=AssertionError("Output preferences must not analyse audio"))
    monkeypatch.setattr(worker, "analyze_file", analyse)
    second, result = run(library, tracks[:1], changed)
    analyse.assert_not_called()
    assert loads(result[tracks[0]]["analysis_json"])["cached"]
    current = repo.list_candidates_for_job(second)
    assert len(current) == 2 and {c["type"] for c in current} == {"INTRO_START", "VOCAL_START"}
    copied = next(c for c in current if c["type"] == "INTRO_START")
    assert copied["id"] != chosen["id"] and copied["edited_time_ms"] == 500 and copied["accepted"]
    assert dict(repo.get_feature_summary(copied["run_id"]), run_id="same") == dict(repo.get_feature_summary(chosen["run_id"]), run_id="same")
    repo.upsert_decision(candidate_id=copied["id"], accepted=False, cue_kind="HOT")
    assert [dict(c) for c in repo.list_candidates_for_job(first)] == previous
    _, repeated = run(library, tracks[:1], changed)
    assert repeated[tracks[0]]["run_id"] == copied["run_id"]
    analyse.assert_not_called()


def test_standard_analysis_hashes_each_source_once_per_submission(library, monkeypatch):
    _, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    hash_audio = Mock(wraps=fingerprint.audio_fingerprint)
    monkeypatch.setattr(fingerprint, "audio_fingerprint", hash_audio)
    run(library, tracks[:1], params)
    hash_audio.assert_called_once()
    hash_audio.reset_mock()
    _, reused = run(library, tracks[:1], params)
    hash_audio.assert_called_once()
    assert loads(reused[tracks[0]]["analysis_json"])["cached"]


def test_audio_changed_during_feature_analysis_is_not_saved(library, monkeypatch):
    repo, _, tracks, _ = library
    params = JobParams(bpm=120, cue_targets=["INTRO_START"]).model_dump()
    analyse = pipeline.analyze_waveform

    def changed(*args, **kwargs):
        result = analyse(*args, **kwargs)
        source = Path(repo.get_track(tracks[0])["path"])
        source.write_bytes(source.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(pipeline, "analyze_waveform", changed)
    job, result = run(library, tracks[:1], params)
    assert result[tracks[0]]["status"] == "FAILED"
    assert "音源が変更" in loads(result[tracks[0]]["analysis_json"])["reason"]
    assert repo.get_job(job)["failed"] == 1
    assert repo.list_candidates_for_job(job) == []


def test_changed_presets_export_new_colors_and_kind_without_reanalysis(library, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    repo, _, tracks, _ = library
    source = repo.get_track(tracks[0])["path"]
    params = {"bpm": 120, "cue_targets": ["INTRO_START"],
              "cue_default": {"cue_kind": "MEMORY", "memory_color": "#00ffff", "hot_color": "#ff0000"}}
    analyse = Mock(wraps=worker.analyze_file)
    monkeypatch.setattr(worker, "analyze_file", analyse)
    with TestClient(app) as client:
        auth = {"Authorization": f"Bearer {app.state.token}"}
        content_id = new_id()

        def submit(settings):
            response = client.post("/api/v1/jobs", headers=auth,
                                   json={"params": settings, "tracks": [{"content_id": content_id, "path": source}]})
            assert response.status_code == 201
            job = response.json()["job_id"]
            for _ in range(300):
                summary = client.get(f"/api/v1/jobs/{job}", headers=auth).json()
                if summary["status"] in {"COMPLETED", "FAILED"}:
                    assert summary["status"] == "COMPLETED" and summary["failed"] == 0
                    return job, client.get(f"/api/v1/jobs/{job}/candidates", headers=auth).json()["candidates"]
                time.sleep(.02)
            raise AssertionError("Job did not finish")

        first, candidates = submit(params)
        accepted = client.post(f"/api/v1/jobs/{first}/candidates/accept", headers=auth,
                               json={"candidate_ids": [candidates[0]["id"]], "cue_kind": "PRESET"})
        assert accepted.status_code == 200
        changed = {**params, "cue_default": {"cue_kind": "HOT", "memory_color": "#9900ff", "hot_color": "#0000ff"}}
        second, copied = submit(changed)
        accepted = client.post(f"/api/v1/jobs/{second}/candidates/accept", headers=auth,
                               json={"candidate_ids": [copied[0]["id"]], "cue_kind": "PRESET"})
        assert accepted.status_code == 200
        analyse.assert_called_once()
        for job, expected_kind, expected_rgb in ((first, "-1", (0, 255, 255)), (second, "0", (0, 0, 255))):
            response = client.post("/api/v1/write/export-xml", headers=auth, json={"job_id": job, "mode": "COPY"})
            assert response.status_code == 200, response.text
            marks = ET.parse(response.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
            assert len(marks) == 1 and marks[0].get("Num") == expected_kind
            assert tuple(int(marks[0].get(key)) for key in ("Red", "Green", "Blue")) == expected_rgb
