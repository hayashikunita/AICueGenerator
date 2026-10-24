import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import time
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient

from app.analysis import ai
from app.analysis.ai_progress import inference_progress
from app.analysis.vocal_scan import scan_vocals
from app.analysis.vocals import vocal_start_from_stems
from app.analysis.pipeline import analyze_waveform
from app.analysis.synth import synthesize_edm
from app.schemas.jobs import JobParams
from app.common import new_id
from app.main import app
from helpers import write_wav


def scan(duration=120, voice_start=4, voice_length=4, level=.1, tags=()):
    calls = []

    def separate(start, end):
        calls.append((start, end))
        times = np.arange(math.ceil(end / .1) - round(start / .1)) * .1 + start
        voice = np.where((times >= voice_start) & (times < voice_start + voice_length), level, 0.)
        for left, right in tags:
            voice[(times >= left) & (times < right)] = .1
        return [.2] * len(times), voice.tolist()

    result = scan_vocals(duration, separate)
    return result, calls


def test_early_voice_stops_after_first_window_and_keeps_only_vocal():
    result, calls = scan()
    assert calls == [(0, 30)]
    assert result["analyzed_sec"] == 30 and result["duration_sec"] == 120
    assert result["scan_complete"] is False
    assert set(result["stems"]) == {"vocals"}
    assert vocal_start_from_stems(result) == pytest.approx(4)
    ai.validate_stems(result)


@pytest.mark.parametrize("start", [29.5, 31, 65])
def test_voice_near_window_boundary_or_late_in_song_is_not_lost(start):
    result, calls = scan(voice_start=start)
    assert len(calls) >= 2
    assert result["analyzed_sec"] >= start + 3
    assert vocal_start_from_stems(result) == pytest.approx(start)


def test_short_tag_does_not_stop_scan_before_later_voice():
    result, calls = scan(voice_start=65, tags=[(2, 2.7)])
    assert len(calls) == 3
    assert vocal_start_from_stems(result) == pytest.approx(65)


def test_ambiguous_quiet_voice_and_instrumental_are_checked_to_song_end():
    quiet, calls = scan(duration=93.23, level=.028)
    assert len(calls) == 4 and quiet["scan_complete"]
    assert quiet["analyzed_sec"] == 93.23
    assert vocal_start_from_stems(quiet) == pytest.approx(4)
    instrumental, calls = scan(duration=93.23, voice_start=200)
    assert len(calls) == 4 and vocal_start_from_stems(instrumental) is None
    ai.validate_stems(instrumental)


def test_repeated_window_percentages_still_terminate_at_song_end_without_repeating_ranges():
    calls, windows = [], []
    duration = 250.98448979591836

    def separate(start, end):
        calls.append((start, end))
        count = math.ceil(end / .1) - round(start / .1)
        return [.2] * count, [0] * count

    result = scan_vocals(duration, separate, on_window=windows.append)
    assert len(calls) == 9
    assert [start for start, _ in calls] == list(range(0, 241, 30))
    assert calls[-1] == (240, duration)
    assert [w["scan_start_sec"] for w in windows] == list(range(0, 241, 30))
    assert result["scan_complete"] and result["analyzed_sec"] == duration


@pytest.mark.parametrize("change", [
    lambda d: d.update(analyzed_sec=121), lambda d: d.update(scan_complete=True),
    lambda d: d.update(analyzed_sec=float("nan")), lambda d: d["stems"]["vocals"].pop(),
    lambda d: d.update(scope="FULL"),
])
def test_invalid_partial_cache_is_rejected(change):
    result, _ = scan()
    change(result)
    with pytest.raises(ValueError):
        ai.validate_stems(result)


def test_full_cache_is_reused_for_vocal_without_running_model(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"original")
    partial, _ = scan(duration=30)
    full = {**partial, "schema": 1, "stems": {"vocals": partial["stems"]["vocals"],
        **{name: [0] * 300 for name in ("drums", "bass", "other")}}}
    from app.config import get_settings
    from app.analysis.fingerprint import audio_fingerprint
    key = hashlib.sha256((ai.AI_REVISION + audio_fingerprint(str(source))).encode()).hexdigest()
    cache = get_settings().data_dir / "ai-cache"
    cache.mkdir(exist_ok=True)
    (cache / f"{key}.json").write_text(json.dumps(full), encoding="utf-8")
    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Must reuse cache"))
    result, reused = ai.analyze_stems(str(source), vocal_only=True)
    assert reused and result["schema"] == 2 and set(result["stems"]) == {"vocals"}
    ai.validate_stems(result)


def test_full_and_vocal_cache_are_separate_and_partial_data_cannot_poison_full_analysis(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"unique scan test")
    calls = []

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            calls.append(args)
            result, _ = scan(duration=120)
            if "--vocal-only" not in args:
                result, _ = scan(duration=30)
                result.update(schema=1, duration_sec=30)
                result["stems"].update({name: [0] * 300 for name in ("drums", "bass", "other")})
            Path(args[args.index("--output") + 1]).write_text(json.dumps(result), encoding="utf-8")

        def poll(self):
            return 0

    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    assert ai.analyze_stems(str(source), vocal_only=True)[1] is False
    assert ai.analyze_stems(str(source), vocal_only=True)[1] is True
    assert ai.analyze_stems(str(source), vocal_only=False)[1] is False
    assert len(calls) == 2 and "--vocal-only" in calls[0] and "--vocal-only" not in calls[1]
    assert source.read_bytes() == b"unique scan test"


def test_scan_range_progress_does_not_reuse_previous_window_percentage(tmp_path):
    path = tmp_path / "scan.log"
    prefix = '\r100%|#| 1/1 [00:05<00:00, 1seconds/s]\nAICUE_SCAN {"scope":"VOCAL","scan_start_sec":30,"scan_end_sec":60,"audio_duration_sec":120}\n'
    path.write_text(prefix, encoding="utf-8")
    assert inference_progress(path)["percent"] is None
    path.write_text(prefix+'\r25%|#| 1/4 [00:04<00:12, 1seconds/s]', encoding="utf-8")
    progress = inference_progress(path)
    assert progress["percent"] == 25 and progress["scan_start_sec"] == 30 and progress["scan_end_sec"] == 60


def test_partial_voice_does_not_change_intro_outro_analysis():
    audio = synthesize_edm(sr=8000)
    config = {"targets": ["INTRO_START", "INTRO_END", "OUTRO", "OUTRO_END"]}
    before = analyze_waveform(audio.y, audio.sr, bpm=audio.bpm, intro_outro=config)
    stems, _ = scan(duration=len(audio.y) / audio.sr)
    after = analyze_waveform(audio.y, audio.sr, bpm=audio.bpm, intro_outro=config, stem_analysis=stems)
    assert before.candidates == after.candidates


def test_vocal_scope_skips_ai_when_no_vocal_is_selected_and_old_api_keeps_full_scope():
    assert JobParams(analysis_quality="AI").ai_scope == "FULL"
    assert JobParams(analysis_quality="AI", ai_scope="VOCAL", cue_targets=["INTRO_END"]).analysis_quality == "STANDARD"
    assert JobParams(analysis_quality="AI", ai_scope="VOCAL", cue_mode="INTRO_OUTRO", intro_outro={"targets": ["VOCAL_START"]}).analysis_quality == "AI"


def test_partial_vocal_scan_flows_through_worker_review_and_xml(tmp_path, monkeypatch):
    data, _ = scan()
    source = write_wav(tmp_path / "voice.wav", np.ones(120 * 8000) * .2, 8000)
    original = source.read_bytes()
    calls = []

    def separate(*args, vocal_only, **kwargs):
        calls.append(vocal_only)
        return data, False

    monkeypatch.setattr("app.api.routes_jobs.ai_status", lambda: {"available": True})
    monkeypatch.setattr("app.jobs.worker.analyze_stems", separate)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", headers=headers, json={"params": {"cue_mode": "INTRO_OUTRO",
            "analysis_quality": "AI", "ai_scope": "VOCAL", "bpm": 120, "intro_outro": {"targets": ["VOCAL_START"]},
            "cue_settings": {"VOCAL_START": {"cue_kind": "HOT", "hot_color": "#00ff00"}}},
            "tracks": [{"content_id": new_id(), "path": str(source)}]})
        assert response.status_code == 201, response.text
        job = response.json()["job_id"]
        for _ in range(200):
            status = client.get(f"/api/v1/jobs/{job}", headers=headers).json()
            if status["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(.03)
        assert status["status"] == "COMPLETED" and status["failed"] == 0
        assert calls == [True]
        track = client.get(f"/api/v1/jobs/{job}/tracks", headers=headers).json()["tracks"][0]
        assert track["analysis"]["vocal_analyzed_sec"] == 30
        assert track["analysis"]["vocal_scan_complete"] is False
        candidates = client.get(f"/api/v1/jobs/{job}/candidates", headers=headers).json()["candidates"]
        assert len(candidates) == 1 and candidates[0]["accepted"] is None and candidates[0]["time_ms"] == 4000
        accepted = client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=headers,
            json={"candidate_ids": [candidates[0]["id"]], "cue_kind": "PRESET"})
        assert accepted.status_code == 200
        exported = client.post("/api/v1/write/export-xml", headers=headers, json={"job_id": job})
        assert exported.status_code == 200, exported.text
        marks = ET.parse(exported.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
        assert len(marks) == 1 and marks[0].get("Name") == "歌い始め" and marks[0].get("Num") != "-1"
        assert tuple(int(marks[0].get(key)) for key in ("Red", "Green", "Blue")) == (0, 255, 0)
    assert source.read_bytes() == original
