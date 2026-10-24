import numpy as np
import pytest

from app.analysis.intro_outro import intro_outro_candidates
from app.analysis.vocals import vocal_start_from_stems
from app.analysis.pipeline import analyze_file
from app.analysis.features import BeatFeatures
from app.domain.models import BeatGrid, PhraseSection
from app.domain.enums import BeatSource
from helpers import write_wav


def envelope(duration=12, hop=.1, start=6, length=2):
    count = round(duration / hop)
    vocals = np.zeros(count)
    vocals[round(start / hop):round((start + length) / hop)] = .1
    return {"hop_sec": hop, "mix": [.2] * count, "stems": {"vocals": vocals.tolist()}}


def test_short_early_shout_is_skipped_before_sustained_voice():
    data = envelope()
    data["stems"]["vocals"][10:17] = [.15] * 7
    assert vocal_start_from_stems(data) == pytest.approx(6)


def test_adaptive_dominance_rejects_continuous_instrument_bleed():
    data = envelope()
    data["stems"]["vocals"][:60] = [.035] * 60
    assert vocal_start_from_stems(data) == pytest.approx(6)


def test_quiet_leading_syllable_is_recovered_without_backtracking_to_an_earlier_tag():
    data = envelope()
    data["stems"]["vocals"][10:13] = [.1] * 3
    data["stems"]["vocals"][58:60] = [.03] * 2
    assert vocal_start_from_stems(data) == pytest.approx(5.8)


def test_word_gaps_are_allowed_but_regular_short_attacks_are_rejected():
    data = envelope()
    for index in range(0, 55, 5):
        data["stems"]["vocals"][index] = .12
    data["stems"]["vocals"][66:68] = [0, 0]
    data["stems"]["vocals"][73:75] = [0, 0]
    assert vocal_start_from_stems(data) == pytest.approx(6)


def test_long_silent_intro_does_not_zero_the_voice_reference():
    assert vocal_start_from_stems(envelope(duration=120, start=110)) == pytest.approx(110)


def test_sustained_voice_can_start_at_zero_and_be_quiet_relative_to_mix():
    data = envelope(start=0)
    data["stems"]["vocals"][:20] = [.028] * 20
    assert vocal_start_from_stems(data) == 0


@pytest.mark.parametrize("hop", [.02, .1, .25, .5])
def test_duration_rules_use_seconds_independently_of_envelope_hop(hop):
    data = envelope(hop=hop)
    for i in range(round(1 / hop), round(1.5 / hop)):
        data["stems"]["vocals"][i] = .1
    assert vocal_start_from_stems(data) == pytest.approx(6)


def test_instrumental_and_short_ending_fragment_do_not_create_vocal_cues():
    assert vocal_start_from_stems(envelope(start=20)) is None
    assert vocal_start_from_stems(envelope(start=11.2, length=.8)) is None


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(hop_sec=float("nan")),
    lambda d: d.update(hop_sec=0),
    lambda d: d["mix"].pop(),
    lambda d: d["stems"]["vocals"].__setitem__(0, float("nan")),
    lambda d: d["stems"]["vocals"].__setitem__(0, -1),
])
def test_invalid_envelopes_cannot_produce_onsets(mutate):
    data = envelope()
    mutate(data)
    assert vocal_start_from_stems(data) is None


def test_specialized_voice_uses_beat_and_never_substitutes_verse_head():
    times = np.arange(32) * .5 + .137
    grid = BeatGrid(120, tuple(times), tuple(range(0, 32, 4)), BeatSource.ANLZ)
    feat = BeatFeatures(times, np.ones(32), np.ones(32), np.zeros(32), np.zeros(32))
    sections = (PhraseSection(0, 8, "INTRO"), PhraseSection(8, 24, "VERSE"))
    config = {"targets": ["VOCAL_START"]}
    candidates, warnings = intro_outro_candidates(feat, grid, [], sections, config, 16)
    assert not candidates and "Verse先頭の置き換えは行いません" in warnings[0]
    candidates, warnings = intro_outro_candidates(feat, grid, [], sections, config, 16,
        vocal_start=6.2, vocal_start_source="DEMUCS")
    assert not warnings and len(candidates) == 1
    assert candidates[0].time_sec == times[12]
    assert not candidates[0].phrase_aligned
    assert "6.200秒" in candidates[0].evidence[0].detail


def test_specialized_lrc_priority_voice_selection_and_fingerprint(tmp_path):
    sr = 8000
    path = write_wav(tmp_path / "voice.wav", np.sin(np.arange(sr * 12) * .2) * .2, sr)
    original = path.read_bytes()
    data = envelope()
    config = {"targets": ["VOCAL_START"]}
    first = analyze_file(str(path), bpm=120, intro_outro=config, stem_analysis=data)
    assert first.candidates[0].time_sec == 6
    path.with_suffix(".lrc").write_text("[00:02.000]Words", encoding="utf-8")
    second = analyze_file(str(path), bpm=120, intro_outro=config, stem_analysis=data)
    assert second.candidates[0].time_sec == 2 and "LRC" in second.candidates[0].evidence[0].detail
    assert first.fingerprint != second.fingerprint
    ignored = analyze_file(str(path), bpm=120, intro_outro={"targets": ["TRACK_END"]}, stem_analysis=data)
    assert all(c.cue_type.value != "VOCAL_START" for c in ignored.candidates)
    assert path.read_bytes() == original
