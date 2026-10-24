import hashlib
import json
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis import ai
from app.analysis.fingerprint import audio_fingerprint
from app.analysis.pipeline import analyze_file, analyze_waveform
from app.analysis.vocal_scan import scan_vocals
from app.analysis.vocals import vocal_end_from_stems, vocal_start_from_stems
from app.common import new_id
from app.config import get_settings
from app.domain.enums import BeatSource
from app.domain.models import BeatGrid, PhraseSection
from app.main import app
from app.schemas.jobs import JobParams
from helpers import write_wav


def envelope(duration=120, voices=((4, 8), (64, 68))):
    times = np.arange(math.ceil(duration / .1)) * .1
    voice = np.zeros(len(times))
    for start, end in voices:
        voice[(times >= start) & (times < end)] = .1
    return {"schema": 2, "model": "htdemucs", "scope": "VOCAL", "hop_sec": .1,
            "duration_sec": duration, "analyzed_sec": duration, "scan_complete": True,
            "mix": [.2] * len(times), "stems": {"vocals": voice.tolist()}}


def test_last_sustained_voice_after_a_long_break_excludes_short_terminal_sounds_and_bleed():
    data = envelope()
    data["stems"]["vocals"][1000:1007] = [.15] * 7
    data["stems"]["vocals"][1010:] = [.035] * 190
    assert vocal_start_from_stems(data) == pytest.approx(4)
    assert vocal_end_from_stems(data) == pytest.approx(68)


def test_word_gaps_and_quiet_trailing_syllable_are_retained():
    data = envelope()
    data["stems"]["vocals"][660:662] = [0, 0]
    data["stems"]["vocals"][680:682] = [.03, .03]
    assert vocal_end_from_stems(data) == pytest.approx(68.2)


def test_non_integral_song_end_is_clamped_to_actual_audio_duration():
    data = envelope(duration=13.23, voices=((10, 14),))
    assert vocal_end_from_stems(data) == pytest.approx(13.23)


@pytest.mark.parametrize("change", [
    lambda d: d.update(scan_complete=False, analyzed_sec=30),
    lambda d: d.update(analyzed_sec=30),
    lambda d: d.update(schema=9),
    lambda d: d.update(duration_sec=float("nan")),
    lambda d: d["mix"].pop(),
    lambda d: d["stems"]["vocals"].__setitem__(100, float("nan")),
])
def test_partial_or_invalid_data_never_supplies_a_final_end(change):
    data = envelope()
    change(data)
    assert vocal_end_from_stems(data) is None


def test_instrumental_and_only_short_voice_are_omitted():
    assert vocal_end_from_stems(envelope(voices=())) is None
    assert vocal_end_from_stems(envelope(voices=((110, 110.7),))) is None


def test_complete_scan_does_not_stop_at_early_voice():
    data = envelope(duration=93.23)
    calls = []

    def separate(start, end):
        calls.append((start, end))
        left, right = round(start / .1), math.ceil(end / .1)
        return data["mix"][left:right], data["stems"]["vocals"][left:right]

    result = scan_vocals(93.23, separate, require_end=True)
    assert calls == [(0, 30), (30, 60), (60, 90), (90, 93.23)]
    assert result["scan_complete"] and vocal_end_from_stems(result) == pytest.approx(68)


@pytest.mark.parametrize("existing_complete", [False, True])
def test_end_cache_reuses_complete_voice_but_never_partial_start_cache(tmp_path, monkeypatch, existing_complete):
    source = tmp_path / "source.wav"
    source.write_bytes(b"full-vocal-cache" + bytes([existing_complete]))
    full = envelope()
    cached = full if existing_complete else {**full, "analyzed_sec": 30, "scan_complete": False,
        "mix": full["mix"][:300], "stems": {"vocals": full["stems"]["vocals"][:300]}}
    cache = get_settings().data_dir / "ai-cache"
    cache.mkdir(exist_ok=True)
    key = hashlib.sha256((ai.VOCAL_REVISION + audio_fingerprint(str(source))).encode()).hexdigest()
    original = json.dumps(cached)
    (cache / f"{key}.json").write_text(original, encoding="utf-8")
    calls = []

    class Process:
        returncode = 0

        def __init__(self, args, **kwargs):
            calls.append(args)
            assert "--vocal-only" in args and "--vocal-end" in args
            Path(args[args.index("--output") + 1]).write_text(json.dumps(full), encoding="utf-8")

        def poll(self):
            return 0

    monkeypatch.setattr(ai, "ai_status", lambda: {"available": True})
    monkeypatch.setattr(ai.subprocess, "Popen", Process)
    result, reused = ai.analyze_stems(str(source), vocal_only=True, require_end=True)
    assert reused == existing_complete and len(calls) == (0 if existing_complete else 1)
    assert result["scan_complete"] and vocal_end_from_stems(result) == pytest.approx(68)
    assert ai.analyze_stems(str(source), vocal_only=True, require_end=True)[1] is True
    assert (cache / f"{key}.json").read_text(encoding="utf-8") == original


def mode_params(mode, start=False):
    targets = ["VOCAL_START", "VOCAL_END"] if start else ["VOCAL_END"]
    if mode == "LEGACY":
        return {"legacy_vocal_end": True, "legacy_vocal_start": start}
    if mode == "INTRO_OUTRO":
        return {"cue_mode": mode, "intro_outro": {"targets": targets}}
    return {"cue_mode": mode, "cue_targets": targets}


@pytest.mark.parametrize("mode", ["LEGACY", "PURPOSE", "INTRO_OUTRO"])
def test_end_only_schemas_keep_ai_enabled_and_snap_to_saved_beat(tmp_path, mode):
    params = JobParams(**mode_params(mode), analysis_quality="AI", ai_scope="VOCAL")
    assert params.analysis_quality == "AI"
    audio = np.ones(12 * 8000) * .2
    source = write_wav(tmp_path / "voice.wav", audio, 8000)
    source.with_suffix(".lrc").write_text("[00:09.000]Last line starts here", encoding="utf-8")
    times = tuple(np.arange(24) * .5 + .137)
    grid = BeatGrid(120, times, tuple(range(0, 24, 4)), BeatSource.ANLZ)
    data = envelope(duration=12, voices=((2, 4), (6, 8.3)))
    kwargs = mode_params(mode)
    kwargs.pop("cue_mode", None)
    result = analyze_file(str(source), beatgrid=grid, stem_analysis=data, **kwargs)
    voice = [c for c in result.candidates if c.cue_type.value == "VOCAL_END"]
    assert len(voice) == 1 and voice[0].time_sec == pytest.approx(8.137)
    assert voice[0].phrase_aligned is False and "8.300秒" in voice[0].evidence[0].detail
    assert not any(c.cue_type.value == "VOCAL_START" for c in result.candidates)
    missing = analyze_file(str(source), beatgrid=grid, **kwargs)
    assert not any(c.cue_type.value == "VOCAL_END" for c in missing.candidates)
    assert any("ボーカルの終わり" in warning for warning in missing.warnings)


def test_end_outside_audio_and_missing_voice_never_substitute_verse_end():
    result = analyze_waveform(np.ones(12 * 8000) * .2, 8000, bpm=120,
        cue_targets=["VOCAL_END"], vocal_end=20, phrase_sections=(PhraseSection(0, 20, "VERSE"),))
    assert not result.candidates


@pytest.mark.parametrize("mode", ["LEGACY", "PURPOSE", "INTRO_OUTRO"])
def test_worker_review_and_colored_both_xml_preserve_original_audio(tmp_path, monkeypatch, mode):
    source = write_wav(tmp_path / "voice.wav", np.ones(12 * 8000) * .2, 8000)
    original = source.read_bytes()
    data = envelope(duration=12, voices=((2, 4), (6, 8.3)))
    calls = []

    def separate(*args, vocal_only, require_end, **kwargs):
        calls.append((vocal_only, require_end))
        return data, True

    monkeypatch.setattr("app.api.routes_jobs.ai_status", lambda: {"available": True})
    monkeypatch.setattr("app.jobs.worker.analyze_stems", separate)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", headers=headers, json={"params": {
            **mode_params(mode, start=True), "analysis_quality": "AI", "ai_scope": "VOCAL", "bpm": 120,
            "cue_settings": {"VOCAL_END": {"cue_kind": "BOTH", "memory_color": "#9900ff", "hot_color": "#00ff00"}}},
            "tracks": [{"content_id": new_id(), "path": str(source)}]})
        assert response.status_code == 201, response.text
        job = response.json()["job_id"]
        for _ in range(200):
            status = client.get(f"/api/v1/jobs/{job}", headers=headers).json()
            if status["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(.03)
        assert status["status"] == "COMPLETED" and status["failed"] == 0
        assert calls == [(True, True)]
        track = client.get(f"/api/v1/jobs/{job}/tracks", headers=headers).json()["tracks"][0]
        assert track["analysis"]["vocal_end_sec"] == pytest.approx(8.3)
        assert track["analysis"]["vocal_end_requested"] is True
        assert track["analysis"]["vocal_scan_complete"] is True
        candidates = client.get(f"/api/v1/jobs/{job}/candidates", headers=headers).json()["candidates"]
        assert all(c["accepted"] is None for c in candidates)
        assert {"VOCAL_START", "VOCAL_END"} <= {c["type"] for c in candidates}
        end = next(c for c in candidates if c["type"] == "VOCAL_END")
        assert end["time_ms"] == 8500
        accepted = client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=headers,
            json={"candidate_ids": [end["id"]], "cue_kind": "PRESET"})
        assert accepted.status_code == 200, accepted.text
        exported = client.post("/api/v1/write/export-xml", headers=headers, json={"job_id": job})
        assert exported.status_code == 200, exported.text
        marks = ET.parse(exported.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
        assert len(marks) == 2 and all(m.get("Name") == "ボーカルの終わり" for m in marks)
        for mark in marks:
            assert tuple(int(mark.get(k)) for k in ("Red", "Green", "Blue")) == ((153, 0, 255) if mark.get("Num") == "-1" else (0, 255, 0))
    assert source.read_bytes() == original
