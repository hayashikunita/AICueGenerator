from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from app.analysis.cue_targets import lyric_start, target_candidates
from app.analysis.features import BeatFeatures
from app.analysis.pipeline import analyze_file, analyze_waveform
from app.analysis.synth import synthesize_edm
from app.domain.enums import BeatSource
from app.domain.models import BeatGrid, PhraseSection
from app.rekordbox import reader
from helpers import write_wav


TARGETS = ["INTRO_START", "OUTRO", "CHORUS_START", "CHORUS_END", "CHORUS_END_MINUS_8_BARS", "VOCAL_START"]


@pytest.fixture
def phrased_grid():
    times = tuple(.137 + i * .5 + i // 32 * .05 for i in range(260))
    grid = BeatGrid(120, times, tuple(range(2, 260, 4)), BeatSource.ANLZ)
    feat = BeatFeatures(np.array(times), np.ones(260), np.ones(260), np.zeros(260), np.zeros(260))
    sections = (PhraseSection(2, 34, "INTRO"), PhraseSection(34, 66, "VERSE"), PhraseSection(66, 130, "CHORUS"),
                PhraseSection(130, 162, "VERSE"), PhraseSection(162, 226, "CHORUS"), PhraseSection(226, 258, "OUTRO"))
    return grid, feat, sections


def test_all_requested_positions_follow_real_grid_and_pair_chorus_ends(phrased_grid):
    grid, feat, sections = phrased_grid
    candidates, warnings = target_candidates(feat, grid, [], TARGETS, sections)
    by_type = {target: [c for c in candidates if c.cue_type.value == target] for target in TARGETS}
    assert {target for target, rows in by_type.items() if rows} == set(TARGETS)
    assert [c.beat_index for c in by_type["CHORUS_START"]] == [66, 162]
    assert [c.beat_index for c in by_type["CHORUS_END"]] == [130, 226]
    assert [c.beat_index for c in by_type["CHORUS_END_MINUS_8_BARS"]] == [98, 194]
    for end, before in zip(by_type["CHORUS_END"], by_type["CHORUS_END_MINUS_8_BARS"]):
        assert grid.downbeat_indices.index(end.beat_index) - grid.downbeat_indices.index(before.beat_index) == 8
        assert end.time_sec - before.time_sec != pytest.approx(16, abs=.001)  # variable tempo: never a seconds subtraction
    assert all(c.time_sec == grid.beat_times[c.beat_index] for c in candidates)
    assert by_type["VOCAL_START"][0].confidence == 30
    assert "歌声は検出していない" in by_type["VOCAL_START"][0].evidence[0].detail
    assert any("仮候補" in warning for warning in warnings)


def test_short_chorus_does_not_invent_negative_or_preceding_section_position(phrased_grid):
    grid, feat, _ = phrased_grid
    candidates, warnings = target_candidates(feat, grid, [], ["CHORUS_END_MINUS_8_BARS"], (PhraseSection(66, 82, "CHORUS"),))
    assert candidates == [] and any("8小節より短い" in warning for warning in warnings)


def test_missing_voice_and_chorus_return_reasons_not_zero_second_guesses(phrased_grid):
    grid, feat, _ = phrased_grid
    candidates, warnings = target_candidates(feat, grid, [], ["VOCAL_START", "CHORUS_START", "CHORUS_END"], ())
    assert candidates == [] and len(warnings) == 3


def test_partial_chorus_end_outside_grid_does_not_clamp_to_last_beat(phrased_grid):
    grid, feat, _ = phrased_grid
    candidates, warnings = target_candidates(feat, grid, [], ["CHORUS_START", "CHORUS_END"], (PhraseSection(66, 500, "CHORUS"),))
    assert len(candidates) == 1 and candidates[0].cue_type.value == "CHORUS_START"
    assert any("サビの終わり" in warning for warning in warnings)
    assert not any("サビの始まり：" in warning for warning in warnings)


def test_vocal_lyrics_timestamp_has_priority_over_verse_and_snaps_to_beat(phrased_grid):
    grid, feat, sections = phrased_grid
    candidates, _ = target_candidates(feat, grid, [], ["VOCAL_START"], sections, vocal_start=20.3)
    assert len(candidates) == 1 and candidates[0].beat_index == 40
    assert candidates[0].beat_index not in grid.downbeat_indices
    assert "LRC" in candidates[0].evidence[0].detail


@pytest.mark.parametrize(("text", "expected"), [
    ("[ar:Artist]\n[ti:Song]\n[00:00.00]\n[00:12.500]Words", 12.5),
    ("[offset:-250]\n[00:10.000]Words", 9.75),
    ("[00:30.0][00:10.0]Words", 10),
    ("[00:00.0]Intro\n[00:01.0][instrumental]\n[00:04.0]歌詞", 4),
    ("[00:00.0]♪♫\n[00:99.0]Invalid\n[99:00.0]Outside", None),
])
def test_lrc_only_uses_real_timed_lyric_lines(text, expected):
    assert lyric_start(text, 60) == expected


@pytest.mark.parametrize(("mood", "chorus", "outro"), [(1, 5, 6), (2, 9, 10), (3, 9, 10)])
def test_pssi_mood_mapping_and_consecutive_chorus_merge(monkeypatch, mood, chorus, outro):
    entries = [SimpleNamespace(beat=1, kind=1), SimpleNamespace(beat=65, kind=chorus),
               SimpleNamespace(beat=97, kind=chorus), SimpleNamespace(beat=129, kind=outro)]
    tag = SimpleNamespace(content=SimpleNamespace(entries=entries, mood=mood, end_beat=161))
    monkeypatch.setattr(reader, "_analysis_tag", lambda *args: (tag, "x.EXT"))
    sections = reader.read_phrases(None, None)["sections"]
    assert sections == [{"start_beat": 0, "end_beat": 64, "kind": "INTRO"},
                        {"start_beat": 64, "end_beat": 128, "kind": "CHORUS"},
                        {"start_beat": 128, "end_beat": 160, "kind": "OUTRO"}]
    tag.content.mood = 999
    assert all(section["kind"] == "UNKNOWN" for section in reader.read_phrases(None, None)["sections"])


def test_selected_targets_filter_pipeline_and_leave_legacy_default_intact():
    track = synthesize_edm(bpm=120, sr=8000)
    default = analyze_waveform(track.y, track.sr, bpm=120)
    assert {c.cue_type.value for c in default.candidates} <= {"INTRO_END", "OUTRO", "BUILD", "BREAK", "DROP"}
    requested = analyze_waveform(track.y, track.sr, bpm=120, cue_targets=["INTRO_START", "CHORUS_END_MINUS_8_BARS"])
    assert requested.candidates
    assert {c.cue_type.value for c in requested.candidates} <= {"INTRO_START", "CHORUS_END_MINUS_8_BARS"}
    assert any("サビとは限らない" in c.evidence[0].detail for c in requested.candidates if c.cue_type.value == "CHORUS_END_MINUS_8_BARS")


def test_lyrics_change_invalidates_fingerprint_and_moves_vocal_candidate(tmp_path):
    track = synthesize_edm(bpm=120, sr=8000, sections=((4, .5, .1),))
    path = write_wav(tmp_path / "lyrics.wav", track.y, track.sr)
    lyrics = path.with_suffix(".lrc")
    lyrics.write_text("[00:01.000]Words", encoding="utf-8")
    first = analyze_file(str(path), bpm=120, cue_targets=["VOCAL_START"])
    lyrics.write_text("[00:03.000]Words", encoding="utf-8")
    second = analyze_file(str(path), bpm=120, cue_targets=["VOCAL_START"])
    assert first.fingerprint != second.fingerprint
    assert first.candidates[0].time_sec == 1 and second.candidates[0].time_sec == 3
    assert lyrics.read_text(encoding="utf-8") == "[00:03.000]Words"
