from dataclasses import replace
import json
import time
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis.features import BeatFeatures
from app.analysis.intro_outro import intro_outro_candidates, fade_end_beat
from app.analysis.pipeline import analyze_waveform
from app.analysis.synth import synthesize_edm
from app.common import new_id
from app.config import get_settings
from app.domain.cue_targets import INTRO_OUTRO_TARGETS, INTRO_OUTRO_DEFAULT_TARGETS, cue_target_label
from app.domain.enums import BeatSource, CueType
from app.domain.models import BeatGrid, PhraseSection
from app.main import app
from app.persistence.repositories import Repository
from app.schemas.jobs import JobParams
from helpers import write_wav


@pytest.fixture
def source():
    n = 550
    times = tuple(.137 + i * .5 + max(0, i - 256) * .07 for i in range(n))
    grid = BeatGrid(120, times, tuple(range(2, n, 4)), BeatSource.ANLZ)
    levels = np.zeros(n)
    levels[2:450] = 1
    levels[450:518] = np.geomspace(1, .005, 68)
    feat = BeatFeatures(np.array(times), levels, np.ones(n), np.zeros(n), np.zeros(n))
    sections = (PhraseSection(2, 130, "INTRO"), PhraseSection(130, 258, "CHORUS"), PhraseSection(386, 514, "OUTRO"))
    config = {"targets": list(INTRO_OUTRO_DEFAULT_TARGETS), "intro_interval_bars": 8, "intro_before_bars": 4,
              "outro_interval_bars": 4, "outro_before_bars": 8, "fade_before_bars": 2, "track_before_bars": 3}
    return feat, grid, sections, config


def run(source, **overrides):
    feat, grid, sections, config = source
    return intro_outro_candidates(feat, grid, [], sections, {**config, **overrides}, grid.beat_times[-1] + .5)


def test_all_specialized_targets_count_actual_bars_in_variable_tempo_and_stay_inside_sections(source):
    candidates, warnings = run(source)
    assert not warnings
    by_type = {target: [c for c in candidates if c.cue_type.value == target] for target in INTRO_OUTRO_DEFAULT_TARGETS}
    assert all(by_type.values())
    expected = {"INTRO_START": [2], "INTRO_BAR": [30], "INTRO_BAR_X2": [62], "INTRO_BAR_X3": [94],
                "INTRO_INTERVAL": [34, 66, 98], "INTRO_END_BEFORE": [114], "INTRO_END": [130],
                "OUTRO": [386], "OUTRO_INTERVAL": [402, 418, 434, 450, 466, 482, 498], "OUTRO_END_BEFORE": [482],
                "OUTRO_END": [514], "FADE_END_BEFORE": [510], "FADE_END": [518], "TRACK_END_BEFORE": [534], "TRACK_END": [546]}
    assert {key: [c.beat_index for c in value] for key, value in by_type.items()} == expected
    grid = source[1]
    assert all(c.beat_index in grid.downbeat_indices and c.time_sec == grid.beat_times[c.beat_index] for c in candidates)
    assert by_type["TRACK_END"][0].time_sec - by_type["TRACK_END_BEFORE"][0].time_sec != pytest.approx(6)
    assert "8小節ごと" in by_type["INTRO_INTERVAL"][0].evidence[0].detail


def test_only_checked_targets_are_generated_and_periodic_targets_are_not_limited_to_top_k(source):
    candidates, _ = run(source, targets=["OUTRO_INTERVAL"], outro_interval_bars=1)
    assert len(candidates) == 31
    assert {c.cue_type for c in candidates} == {CueType.OUTRO_INTERVAL}
    assert [c.rank for c in candidates] == list(range(1, 32))


@pytest.mark.parametrize("base,expected,omitted", [
    (1, [2, 6, 10], 0), (8, [30, 62, 94], 0), (16, [62, 126], 1),
    (32, [126], 2), (33, [], 3), (128, [], 3),
])
def test_intro_ordinal_positions_count_first_bar_as_one_and_exclude_next_section(source, base, expected, omitted):
    candidates, warnings = run(source, targets=["INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3"], intro_position_bars=base)
    assert [c.beat_index for c in candidates] == expected
    assert len(warnings) == omitted
    assert all(2 <= c.beat_index < 130 for c in candidates)
    assert all(c.time_sec == source[1].beat_times[c.beat_index] for c in candidates)
    for candidate in candidates:
        label = cue_target_label(candidate.cue_type.value, {"intro_outro": {"intro_position_bars": base}})
        assert label in candidate.evidence[0].detail


def test_intro_multiplier_can_be_selected_alone_and_uses_shared_base_not_interval(source):
    candidates, warnings = run(source, targets=["INTRO_BAR_X2"], intro_position_bars=5, intro_interval_bars=1)
    assert not warnings and len(candidates) == 1
    assert candidates[0].cue_type == CueType.INTRO_BAR_X2
    assert candidates[0].beat_index == 38  # Tenth bar: first downbeat + nine bars.
    assert "イントロの10小節目" in candidates[0].evidence[0].detail


def test_intro_ordinals_use_saved_variable_tempo_downbeats_with_leading_silence(source):
    feat, grid, _, config = source
    # Intro starts later, after the tempo change; it must not be counted from file start or BPM seconds.
    sections = (PhraseSection(274, 402, "INTRO"),)
    candidates, warnings = intro_outro_candidates(feat, grid, [], sections,
        {**config, "targets": ["INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3"], "intro_position_bars": 8}, grid.beat_times[-1] + .5)
    assert not warnings
    assert [c.beat_index for c in candidates] == [302, 334, 366]
    assert candidates[0].time_sec == grid.beat_times[302]
    assert candidates[0].time_sec - grid.beat_times[274] != pytest.approx(14)


def test_too_many_bars_before_end_does_not_cross_into_another_section_or_clamp_to_zero(source):
    candidates, warnings = run(source, targets=["INTRO_END_BEFORE", "OUTRO_END_BEFORE", "TRACK_END_BEFORE"],
                               intro_before_bars=128, outro_before_bars=128, track_before_bars=128)
    assert [c.cue_type.value for c in candidates] == ["TRACK_END_BEFORE"]
    assert len(warnings) == 2


@pytest.mark.parametrize("amount", [0, -1, 129, 1.5, True])
def test_invalid_bar_counts_cannot_reach_analysis(source, amount):
    with pytest.raises(ValueError, match="小節数"):
        run(source, intro_interval_bars=amount)
    with pytest.raises(ValueError, match="小節数"):
        run(source, intro_position_bars=amount)


def test_fade_detection_distinguishes_gradual_fade_from_abrupt_cut_and_terminal_click():
    fading = np.ones(200)
    fading[100:180] = np.geomspace(1, .005, 80)
    fading[180:] = 0
    fading[198] = 1
    assert fade_end_beat(fading) == 180
    abrupt = np.ones(200)
    abrupt[180:] = 0
    assert fade_end_beat(abrupt) is None
    assert fade_end_beat(np.zeros(200)) is None


def test_absent_fade_only_omits_fade_targets_and_does_not_invent_a_fade_at_file_end(source):
    feat, grid, sections, config = source
    levels = np.ones(len(feat.rms))
    candidates, warnings = intro_outro_candidates(replace(feat, rms=levels), grid, [], sections, config, grid.beat_times[-1] + .5)
    assert not any(c.cue_type.value.startswith("FADE_") for c in candidates)
    assert any(c.cue_type == CueType.TRACK_END for c in candidates)
    assert len(warnings) == 2 and all("フェード終端を確認できません" in warning for warning in warnings)


def test_source_phrase_end_outside_saved_grid_cannot_create_a_beat_past_the_audio(source):
    feat, grid, _, config = source
    candidates, _ = intro_outro_candidates(feat, grid, [], (PhraseSection(386, 999, "OUTRO"),), config, grid.beat_times[-1] + .5)
    assert all(c.beat_index < len(grid.beat_times) for c in candidates)
    assert next(c for c in candidates if c.cue_type == CueType.OUTRO_END).beat_index == 518


def test_specialized_schema_preserves_bar_settings_and_normalizes_unneeded_ai_and_purpose_targets():
    params = JobParams(cue_mode="INTRO_OUTRO", analysis_quality="AI", cue_targets=["VOCAL_START"], intro_outro={"intro_interval_bars": 16, "intro_position_bars": 4})
    assert params.analysis_quality == "STANDARD" and params.cue_targets is None
    assert params.intro_outro.intro_interval_bars == 16
    assert params.intro_outro.intro_position_bars == 4
    assert set(params.intro_outro.targets) == set(INTRO_OUTRO_DEFAULT_TARGETS)
    vocal_params = JobParams(cue_mode="INTRO_OUTRO", analysis_quality="AI", intro_outro={"targets": ["VOCAL_START"]})
    assert vocal_params.analysis_quality == "AI"
    with pytest.raises(ValueError):
        JobParams(cue_mode="INTRO_OUTRO", intro_outro={"targets": ["CHORUS_START"]})
    with pytest.raises(ValueError):
        JobParams(cue_mode="INTRO_OUTRO", intro_outro={"targets": []})


def test_specialized_pipeline_without_vocal_selection_never_generates_other_purposes(monkeypatch):
    from app.analysis import pipeline
    original = pipeline.generate_candidates
    called = []

    def generate(*args, **kwargs):
        called.append(kwargs["cue_types"])
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "generate_candidates", generate)
    track = synthesize_edm(sr=8000)
    result = analyze_waveform(track.y, track.sr, bpm=track.bpm, top_k=1, intro_outro={"targets": ["INTRO_INTERVAL", "TRACK_END"]})
    assert called == [(CueType.INTRO_END, CueType.OUTRO)]
    assert {c.cue_type.value for c in result.candidates} <= {"INTRO_INTERVAL", "TRACK_END"}
    assert any(c.cue_type == CueType.TRACK_END for c in result.candidates)


def test_specialized_api_skips_ai_and_keeps_source_unchanged_and_candidates_unadopted(tmp_path, monkeypatch):
    headers = {"Authorization": f"Bearer {app.state.token}"}
    audio = synthesize_edm(sr=8000)
    path = write_wav(tmp_path / "special.wav", audio.y, audio.sr)
    original = path.read_bytes()
    monkeypatch.setattr("app.jobs.worker.analyze_stems", lambda *args, **kwargs: pytest.fail("Specialized analysis must not separate vocals"))
    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", headers=headers, json={"params": {"cue_mode": "INTRO_OUTRO", "analysis_quality": "AI", "bpm": 128,
            "intro_outro": {"targets": ["INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3", "TRACK_END_BEFORE", "TRACK_END"], "intro_position_bars": 2, "track_before_bars": 4},
            "cue_settings": {"INTRO_BAR": {"cue_kind": "MEMORY", "memory_color": "#ff0000"},
                "INTRO_BAR_X2": {"cue_kind": "HOT", "hot_color": "#0000ff"},
                "INTRO_BAR_X3": {"cue_kind": "BOTH", "memory_color": "#00ff00", "hot_color": "#ffff00"}}},
            "tracks": [{"content_id": new_id(), "path": str(path)}]})
        assert response.status_code == 201, response.text
        job = response.json()["job_id"]
        for _ in range(150):
            status = client.get(f"/api/v1/jobs/{job}", headers=headers).json()
            if status["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(.03)
        assert status["status"] == "COMPLETED" and status["failed"] == 0
        assert status["params"]["intro_outro"]["track_before_bars"] == 4
        assert status["params"]["intro_outro"]["intro_position_bars"] == 2
        candidates = client.get(f"/api/v1/jobs/{job}/candidates", headers=headers).json()["candidates"]
        assert len(candidates) == 5 and all(candidate["accepted"] is None for candidate in candidates)
        assert {c["type"] for c in candidates} == {"INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3", "TRACK_END", "TRACK_END_BEFORE"}
        accepted = client.post(f"/api/v1/jobs/{job}/candidates/accept", headers=headers,
            json={"candidate_ids": [c["id"] for c in candidates if c["type"].startswith("INTRO_BAR")], "cue_kind": "PRESET"})
        assert accepted.status_code == 200, accepted.text
        chosen = next(c for c in candidates if c["type"] == "TRACK_END_BEFORE")
        client.post(f"/api/v1/candidates/{chosen['id']}/decision", headers=headers, json={"accepted": True, "cue_kind": "MEMORY"})
        export = client.post("/api/v1/write/export-xml", headers=headers, json={"job_id": job, "mode": "COPY"})
        assert export.status_code == 200, export.text
        marks = ET.parse(export.json()["xml_path"]).getroot().findall("COLLECTION/TRACK/POSITION_MARK")
        assert len(marks) == 5
        assert {(m.get("Name"), m.get("Num") == "-1"): tuple(int(m.get(k)) for k in ("Red", "Green", "Blue"))
                for m in marks if m.get("Name").startswith("イントロ")} == {
            ("イントロの2小節目", True): (255, 0, 0), ("イントロの4小節目", False): (0, 0, 255),
            ("イントロの6小節目", True): (0, 255, 0), ("イントロの6小節目", False): (255, 255, 0)}
        assert any(m.get("Name") == "曲の終わりから4小節前" for m in marks)
    assert path.read_bytes() == original
