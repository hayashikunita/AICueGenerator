import numpy as np
import pytest

from app.analysis.beatgrid import beat_stability, uniform_beatgrid
from app.analysis.features import extract_features
from app.analysis.fingerprint import audio_fingerprint
from app.analysis.phrases import phrase_grids
from app.analysis.pipeline import analyze_waveform
from app.analysis.scoring import confidence_band, score_candidate
from app.analysis.synth import synthesize_edm
from app.domain.enums import CueType


def _bar_to_beat(bar: int, beats_per_bar: int = 4) -> int:
    return bar * beats_per_bar


def test_uniform_beatgrid_shape_and_downbeats():
    grid = uniform_beatgrid(120.0, 10.0, beats_per_bar=4)
    assert grid.bpm == 120.0
    # 0.5s 間隔なので 10s で 21 拍(0..20)
    assert len(grid.beat_times) == 21
    assert grid.downbeat_indices[0] == 0
    assert grid.downbeat_indices[1] == 4


def test_beat_stability_uniform_is_high():
    grid = uniform_beatgrid(128.0, 30.0)
    assert beat_stability(grid.beat_times) > 0.95


def test_phrase_grids_phase_count():
    grid = uniform_beatgrid(128.0, 120.0, beats_per_bar=4)
    grids = phrase_grids(grid.downbeat_indices, bars_options=(16,))
    assert len(grids) == 16  # 位相 0..15
    assert all(g.bars_per_phrase == 16 for g in grids)


def test_features_low_ratio_higher_for_kick_than_noise():
    sr = 22050
    t = np.arange(sr) / sr
    kick = np.sin(2 * np.pi * 60 * t)
    noise = np.random.default_rng(0).normal(0, 0.3, sr)
    beats = np.array([0.0, 0.5])
    fk = extract_features(kick, sr, beats)
    fn = extract_features(noise, sr, beats)
    assert fk.low_ratio[0] > fn.low_ratio[0]


def test_scoring_weights_sum_and_band():
    conf, ev = score_candidate(
        {
            "beat_stability": 1.0,
            "phrase_alignment": 1.0,
            "energy_diff": 1.0,
            "percussive_onset": 1.0,
            "repetition": 1.0,
        }
    )
    assert conf == 100.0
    assert confidence_band(conf) == "high"
    assert sum(e.weight for e in ev) == 100.0


def test_scoring_pssi_bonus_clips_to_one():
    conf, ev = score_candidate(
        {"phrase_alignment": 0.95}, pssi_bonus=0.2
    )
    phrase = next(e for e in ev if e.name == "フレーズ整合")
    assert phrase.score == 1.0


def test_fingerprint_is_deterministic(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world")
    fp1 = audio_fingerprint(f)
    fp2 = audio_fingerprint(f)
    assert fp1 == fp2 and fp1.startswith("sha256:")


def test_pipeline_detects_drops_and_break_on_phrase_boundaries():
    track = synthesize_edm(bpm=128.0, seed=0)
    result = analyze_waveform(track.y, track.sr, bpm=track.bpm)

    bp = track.beats_per_bar
    # セクション境界: intro0 build16 drop32 break48 drop64 outro80
    drop_beats = {c.beat_index for c in result.candidates if c.cue_type is CueType.DROP}
    break_beats = {c.beat_index for c in result.candidates if c.cue_type is CueType.BREAK}
    outro_beats = {c.beat_index for c in result.candidates if c.cue_type is CueType.OUTRO}

    assert _bar_to_beat(32, bp) in drop_beats
    assert _bar_to_beat(64, bp) in drop_beats
    assert _bar_to_beat(48, bp) in break_beats
    assert _bar_to_beat(80, bp) in outro_beats


def test_pipeline_drop_is_high_confidence():
    track = synthesize_edm(bpm=128.0, seed=0)
    result = analyze_waveform(track.y, track.sr, bpm=track.bpm)
    drops = [c for c in result.candidates if c.cue_type is CueType.DROP]
    assert drops and max(c.confidence for c in drops) >= 80.0


def test_pipeline_candidates_are_phrase_aligned():
    track = synthesize_edm(bpm=128.0, seed=1)
    result = analyze_waveform(track.y, track.sr, bpm=track.bpm)
    assert result.candidates
    assert all(c.phrase_aligned for c in result.candidates)


@pytest.mark.parametrize("beats", [4, 8, 16, 32, 64, 128])
def test_beat_interval_matches_equivalent_bar_interval(beats):
    track = synthesize_edm(bpm=128.0, sr=8000, seed=0)
    by_beats = analyze_waveform(track.y, track.sr, bpm=track.bpm, beats_per_phrase=beats)
    by_bars = analyze_waveform(track.y, track.sr, bpm=track.bpm, bars_per_phrase=beats // 4)
    assert by_beats.candidates
    assert by_beats.candidates == by_bars.candidates
    # 候補は、選択した拍数の境界に同じ位相で整列する。
    assert len({c.beat_index % beats for c in by_beats.candidates}) == 1


def test_analysis_without_rekordbox_estimates_beats_from_audio(monkeypatch):
    from app.analysis import pipeline
    from app.analysis.beatgrid import uniform_beatgrid

    track = synthesize_edm(bpm=120.0, sr=8000)
    calls = []

    def estimate(y, sr, *, beats_per_bar):
        calls.append((len(y), sr))
        return uniform_beatgrid(120.0, len(y) / sr, beats_per_bar=beats_per_bar)

    monkeypatch.setattr(pipeline, "estimate_beatgrid", estimate)
    result = analyze_waveform(track.y, track.sr, beats_per_phrase=8)
    assert calls == [(len(track.y), track.sr)]
    assert result.beatgrid.bpm == 120.0 and result.candidates
