import time
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis.pipeline import analyze_waveform, analyze_file
from app.analysis.synth import synthesize_edm
from app.common import new_id
from app.domain.enums import CueType
from app.domain.models import PhraseSection
from app.main import app
from app.schemas.jobs import JobParams
from helpers import write_wav


@pytest.fixture(scope="module")
def legacy_source():
    audio = synthesize_edm(sr=8000)
    baseline = analyze_waveform(audio.y, audio.sr, bpm=audio.bpm)
    return audio, baseline


def test_legacy_voice_adds_one_candidate_without_replacing_or_changing_original_types(legacy_source):
    audio, baseline = legacy_source
    assert {c.cue_type.value for c in baseline.candidates} == {"INTRO_END", "BREAK", "BUILD", "DROP", "OUTRO"}
    result = analyze_waveform(audio.y, audio.sr, bpm=audio.bpm, legacy_vocal_start=True,
        vocal_start=2.34, vocal_start_source="DEMUCS_VOCAL")
    assert tuple(c for c in result.candidates if c.cue_type != CueType.VOCAL_START) == baseline.candidates
    vocals = [c for c in result.candidates if c.cue_type == CueType.VOCAL_START]
    assert len(vocals) == 1
    assert vocals[0].time_sec == pytest.approx(2.34375)
    assert not vocals[0].phrase_aligned


def test_legacy_missing_voice_keeps_originals_and_does_not_substitute_verse(legacy_source):
    audio, baseline = legacy_source
    result = analyze_waveform(audio.y, audio.sr, bpm=audio.bpm, legacy_vocal_start=True,
        phrase_sections=(PhraseSection(32, 96, "VERSE"),))
    assert result.candidates == baseline.candidates
    assert any("歌い始め" in warning for warning in result.warnings)


def test_legacy_lrc_is_read_only_when_enabled_and_takes_priority(tmp_path):
    path = write_wav(tmp_path / "voice.wav", np.ones(8000 * 12) * .2, 8000)
    path.with_suffix(".lrc").write_text("[00:02.000]Words", encoding="utf-8")
    disabled = analyze_file(str(path), bpm=120)
    assert not any(c.cue_type == CueType.VOCAL_START for c in disabled.candidates)
    data = {"schema": 2, "scope": "VOCAL", "hop_sec": .1, "duration_sec": 12, "analyzed_sec": 12,
        "scan_complete": True, "mix": [.2] * 120, "stems": {"vocals": [0] * 60 + [.1] * 30 + [0] * 30}}
    enabled = analyze_file(str(path), bpm=120, legacy_vocal_start=True, stem_analysis=data)
    vocal = next(c for c in enabled.candidates if c.cue_type == CueType.VOCAL_START)
    assert vocal.time_sec == 2 and "LRC" in vocal.evidence[0].detail
    assert path.with_suffix(".lrc").read_text(encoding="utf-8") == "[00:02.000]Words"


def test_legacy_schema_allows_vocal_scan_without_repurposing_cue_targets():
    params = JobParams(cue_mode="LEGACY", legacy_vocal_start=True, analysis_quality="AI", ai_scope="VOCAL")
    assert params.analysis_quality == "AI" and params.cue_targets is None
    assert JobParams().legacy_vocal_start is False
    assert JobParams(cue_mode="PURPOSE", legacy_vocal_start=True, cue_targets=["INTRO_START"]).legacy_vocal_start is False
    assert JobParams(cue_mode="INTRO_OUTRO", legacy_vocal_start=True).legacy_vocal_start is False


@pytest.mark.parametrize("tracks", [1, 2])
def test_legacy_api_mixes_old_candidates_and_voice_with_presets_and_xml(tmp_path, monkeypatch, legacy_source, tracks):
    audio, _ = legacy_source
    paths = [write_wav(tmp_path / f"source-{i}.wav", audio.y, audio.sr) for i in range(tracks)]
    originals = [path.read_bytes() for path in paths]
    count = 300
    data = {"schema": 2, "model": "htdemucs", "scope": "VOCAL", "hop_sec": .1,
        "duration_sec": len(audio.y) / audio.sr, "analyzed_sec": 30, "scan_complete": False,
        "mix": [.2] * count, "stems": {"vocals": [0] * 30 + [.1] * 40 + [0] * (count - 70)}}
    calls = []

    def separate(*args, vocal_only, **kwargs):
        calls.append(vocal_only)
        return data, False

    monkeypatch.setattr("app.api.routes_jobs.ai_status", lambda: {"available": True})
    monkeypatch.setattr("app.jobs.worker.analyze_stems", separate)
    headers = {"Authorization": f"Bearer {app.state.token}"}
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", headers=headers, json={"params": {"cue_mode": "LEGACY",
            "legacy_vocal_start": True, "analysis_quality": "AI", "ai_scope": "VOCAL", "bpm": audio.bpm,
            "cue_settings": {"VOCAL_START": {"cue_kind": "BOTH", "memory_color": "#9900ff", "hot_color": "#00ff00"}}},
            "tracks": [{"content_id": new_id(), "path": str(path)} for path in paths]})
        assert response.status_code == 201, response.text
        job = response.json()["job_id"]
        for _ in range(400):
            status = client.get(f"/api/v1/jobs/{job}", headers=headers).json()
            if status["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(.03)
        assert status["status"] == "COMPLETED" and status["failed"] == 0
        assert status["params"]["legacy_vocal_start"] and status["params"]["cue_targets"] is None
        assert calls == [True] * tracks
        candidates = client.get(f"/api/v1/jobs/{job}/candidates", headers=headers).json()["candidates"]
        assert {c["type"] for c in candidates} == {"INTRO_END", "BREAK", "BUILD", "DROP", "OUTRO", "VOCAL_START"}
        assert all(c["accepted"] is None for c in candidates)
        voices = [c for c in candidates if c["type"] == "VOCAL_START"]
        assert len(voices) == tracks
        accepted = client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=headers,
            json={"candidate_ids": [c["id"] for c in voices], "cue_kind": "PRESET"})
        assert accepted.status_code == 200, accepted.text
        export = client.post("/api/v1/write/export-xml", headers=headers, json={"job_id": job})
        assert export.status_code == 200, export.text
        marks = ET.parse(export.json()["xml_path"]).getroot().findall(".//POSITION_MARK")
        assert len(marks) == tracks * 2
        assert all(m.get("Name") == "歌い始め" for m in marks)
        for mark in marks:
            assert tuple(int(mark.get(k)) for k in ("Red", "Green", "Blue")) == ((153, 0, 255) if mark.get("Num") == "-1" else (0, 255, 0))
    assert [path.read_bytes() for path in paths] == originals
