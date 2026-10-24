"""Regression scenarios for audible boundaries, independent of live libraries."""
import numpy as np
import pytest

from app.analysis.activity import activity_bounds
from app.analysis.cue_targets import target_candidates
from app.analysis.features import BeatFeatures, extract_features
from app.domain.enums import BeatSource, CueType
from app.domain.models import BeatGrid, CueCandidate, PhraseSection


TARGETS = ["INTRO_START", "INTRO_END", "OUTRO", "OUTRO_END"]


def suggest(levels, *, targets=TARGETS, sections=(), base=(), top_k=3, alignment=1):
    n = len(levels)
    # Offset downbeats and a tempo change expose accidental seconds arithmetic.
    times = tuple(.137 + i * .5 + max(0, i - 128) * .04 for i in range(n))
    grid = BeatGrid(120, times, tuple(range(0, n, 4)), BeatSource.ANLZ)
    feat = BeatFeatures(np.array(times), np.array(levels), np.ones(n), np.zeros(n), np.zeros(n))
    candidates, warnings = target_candidates(feat, grid, list(base), targets, sections,
                                             top_k=top_k, end_alignment_bars=alignment)
    assert all(c.time_sec == times[c.beat_index] for c in candidates)
    assert all(c.beat_index in grid.downbeat_indices for c in candidates)
    return candidates, warnings


def test_quiet_intro_is_kept_instead_of_starting_at_the_loud_section():
    levels = np.ones(128)
    levels[:32] = .01  # Forty dB below the main section; previously omitted.
    candidates, _ = suggest(levels, targets=["INTRO_START"])
    assert [c.beat_index for c in candidates] == [0]


def test_isolated_head_and_tail_clicks_do_not_extend_musical_bounds():
    levels = np.zeros(256)
    levels[16:192] = .01
    levels[0] = levels[248] = 10
    candidates, _ = suggest(levels, targets=["INTRO_START", "OUTRO_END"], alignment=8)
    assert [(c.cue_type.value, c.beat_index) for c in candidates] == [("INTRO_START", 16), ("OUTRO_END", 192)]


def test_quiet_fade_is_included_before_trailing_silence():
    levels = np.zeros(256)
    levels[:64] = 1
    levels[64:224] = np.geomspace(1, .005, 160)
    candidates, _ = suggest(levels, targets=["OUTRO_END"], alignment=8)
    assert [c.beat_index for c in candidates] == [224]


def test_sparse_percussion_still_counts_as_music():
    levels = np.zeros(128)
    levels[16:96:2] = .2
    candidates, _ = suggest(levels, targets=["INTRO_START"])
    assert [c.beat_index for c in candidates] == [16]


@pytest.mark.parametrize("artifacts", [[], [0], [0, 120]])
def test_silence_and_isolated_artifacts_never_create_intro_or_outro(artifacts):
    levels = np.zeros(128)
    levels[artifacts] = 1
    sections = (PhraseSection(0, 32, "INTRO"), PhraseSection(96, 127, "OUTRO"))
    candidates, warnings = suggest(levels, sections=sections)
    assert candidates == [] and len(warnings) == len(TARGETS)


def test_saved_phrase_boundaries_are_kept_when_supported_by_audio():
    sections = (PhraseSection(0, 32, "INTRO"), PhraseSection(192, 224, "OUTRO"))
    candidates, warnings = suggest(np.ones(256), sections=sections, alignment=8)
    assert warnings == []
    assert [(c.cue_type.value, c.beat_index) for c in candidates] == [
        ("INTRO_START", 0), ("INTRO_END", 32), ("OUTRO", 192), ("OUTRO_END", 224)]


def test_saved_phrase_ranges_do_not_put_cues_in_silence_or_after_a_tail_click():
    levels = np.zeros(256)
    levels[16:224] = .5
    levels[248] = 1
    sections = (PhraseSection(0, 32, "INTRO"), PhraseSection(192, 255, "OUTRO"))
    candidates, _ = suggest(levels, sections=sections, alignment=8)
    assert [(c.cue_type.value, c.beat_index) for c in candidates] == [
        ("INTRO_START", 16), ("INTRO_END", 32), ("OUTRO", 192), ("OUTRO_END", 224)]


@pytest.mark.parametrize(("target", "kind"), [("INTRO_END", CueType.INTRO_END), ("OUTRO", CueType.OUTRO)])
def test_top_candidate_uses_strength_instead_of_first_chronological_guess(target, kind):
    base = [CueCandidate(kind, 8, 16, 42, 2), CueCandidate(kind, 16, 32, 84, 1)]
    candidates, _ = suggest(np.ones(128), targets=[target], base=base, top_k=1)
    assert [c.beat_index for c in candidates] == [32]
    assert candidates[0].confidence <= 50  # A fallback never becomes a verified phrase.


def test_end_alignment_deduplicates_candidates_that_snap_to_same_bar():
    base = [CueCandidate(CueType.INTRO_END, 18, 36, 80, 1), CueCandidate(CueType.INTRO_END, 20, 40, 75, 2)]
    candidates, _ = suggest(np.ones(128), targets=["INTRO_END"], base=base, alignment=8)
    assert [c.beat_index for c in candidates] == [32]


def test_activity_uses_decoded_audio_and_handles_nonfinite_levels():
    sr = 8000
    y = np.zeros(sr * 32)
    t = np.arange(sr * 16) / sr
    y[sr * 8:sr * 24] = .02 * np.sin(2 * np.pi * 220 * t)
    y[0] = y[-1] = .9  # Single-sample clicks at the file boundaries.
    features = extract_features(y, sr, np.arange(0, 32, .5))
    bounds = activity_bounds(features.rms)
    assert bounds and (bounds.start_beat, bounds.end_beat) == (16, 48)
    assert activity_bounds(np.array([np.nan, np.inf, -1])) is None
