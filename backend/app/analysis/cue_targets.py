"""Purpose-specific suggestions, keeping source labels and uncertainty explicit."""
from __future__ import annotations

from dataclasses import replace
import re

import numpy as np

from ..domain.enums import CueType
from ..domain.models import BeatGrid, CueCandidate, Evidence, PhraseSection
from ..domain.cue_targets import CUE_TARGET_LABELS as TARGET_LABELS
from .features import BeatFeatures

def lyric_start(text: str, duration: float) -> float | None:
    """Read the earliest timed lyric line (not title/artist metadata) from LRC."""
    offset = re.search(r"\[offset:([+-]?\d{1,9})\]", text, re.I)
    shift = int(offset.group(1)) / 1000 if offset else 0
    times = []
    for line in text.splitlines():
        matches = list(re.finditer(r"\[(\d{1,3}):([0-5]\d(?:[.:]\d{1,3})?)\]", line))
        if not matches:
            continue
        lyric = line[matches[-1].end():].strip()
        if not lyric or re.fullmatch(r"\[.*\]|[♪♫\s]+", lyric) or lyric.casefold() in {"intro", "outro", "instrumental", "間奏", "前奏"}:
            continue
        for match in matches:
            seconds = int(match.group(1)) * 60 + float(match.group(2).replace(":", ".")) + shift
            if 0 <= seconds < duration:
                times.append(seconds)
    return min(times) if times else None


def target_candidates(
    feat: BeatFeatures, grid: BeatGrid, base: list[CueCandidate],
    targets: list[str], sections: tuple[PhraseSection, ...] = (),
    *, top_k: int = 3, vocal_start: float | None = None,
) -> tuple[list[CueCandidate], list[str]]:
    times = np.asarray(grid.beat_times)
    bars = np.asarray(grid.downbeat_indices, dtype=int)
    out: list[CueCandidate] = []
    warnings: list[str] = []
    if not len(bars):
        return [], ["小節頭がないため、指定位置の候補を生成できませんでした。"]

    def bar_index(beat: int) -> int | None:
        if not 0 <= beat < len(times):
            return None
        return int(np.argmin(np.abs(bars - beat)))

    def add(target: str, beat: int, confidence: float, detail: str, *, aligned=True):
        if 0 <= beat < len(times) and sum(c.cue_type.value == target for c in out) < top_k:
            out.append(CueCandidate(CueType(target), float(times[beat]), int(beat), confidence,
                                    1 + sum(c.cue_type.value == target for c in out),
                                    (Evidence("候補の位置と根拠", 100, confidence / 100, detail),), aligned))

    known = any(s.kind != "UNKNOWN" for s in sections)
    choruses: list[tuple[int, int, float, str]] = []
    partial_starts = []
    for section in sections:
        if section.kind != "CHORUS":
            continue
        start, end = bar_index(section.start_beat), bar_index(section.end_beat)
        if start is not None and end is not None and start < end:
            choruses.append((start, end, 85, "rekordbox の Chorus フレーズ境界（曲の正解を保証するものではありません）"))
        elif start is not None:
            partial_starts.append(int(bars[start]))
    if not choruses and not known:
        # An EDM drop is not necessarily a pop chorus. Label this fallback explicitly.
        ends = sorted({c.beat_index for c in base if c.cue_type in (CueType.BREAK, CueType.OUTRO)})
        for drop in sorted((c for c in base if c.cue_type == CueType.DROP), key=lambda c: c.beat_index):
            end = next((b for b in ends if b > drop.beat_index), None)
            if end is not None:
                start_bar, end_bar = bar_index(drop.beat_index), bar_index(end)
                if start_bar is not None and end_bar is not None and start_bar < end_bar:
                    choruses.append((start_bar, end_bar, min(50, drop.confidence), "音量・低域の変化から推定した Drop〜Break/Outro の区間。サビとは限らないため試聴で確認してください。"))

    for target in dict.fromkeys(targets):
        before = len(out)
        if target == "INTRO_START":
            intros = [s for s in sections if s.kind == "INTRO"]
            if intros:
                index = bar_index(intros[0].start_beat)
                if index is not None:
                    add(target, int(bars[index]), 85, "rekordbox の Intro フレーズの先頭")
            elif len(feat.rms) and float(np.max(feat.rms)) > 1e-4:
                active = np.flatnonzero(feat.rms > max(1e-4, float(np.max(feat.rms)) * .03))
                if len(active):
                    choices = bars[bars >= active[0]]
                    if len(choices):
                        add(target, int(choices[0]), 50, "音源の最初の有音部分以降の小節頭。Intro ラベルがないため推定です。")
        elif target == "OUTRO":
            outros = [s for s in sections if s.kind == "OUTRO"]
            if outros:
                index = bar_index(outros[-1].start_beat)
                if index is not None:
                    add(target, int(bars[index]), 85, "rekordbox の Outro フレーズの先頭")
            else:
                for candidate in sorted((c for c in base if c.cue_type == CueType.OUTRO), key=lambda c: c.time_sec):
                    out.append(replace(candidate, rank=1 + len(out) - before))
        elif target.startswith("CHORUS_"):
            for start, end, confidence, detail in choruses:
                bar = start if target == "CHORUS_START" else end
                if target == "CHORUS_END_MINUS_8_BARS":
                    bar = end - 8
                    if bar < start:
                        warnings.append("8小節より短いサビ区間のため、「終わりから8小節前」の候補を省略しました。")
                        continue
                    detail += f"。終了位置 {times[bars[end]]:.3f}秒の小節頭から、実グリッドで8小節前。"
                add(target, int(bars[bar]), confidence, detail)
            if target == "CHORUS_START":
                for beat in partial_starts:
                    add(target, beat, 85, "rekordbox の Chorus 先頭。末尾はグリッド外のため未取得です。")
        elif target == "VOCAL_START":
            if vocal_start is not None and 0 <= vocal_start <= times[-1]:
                beat = int(np.argmin(np.abs(times - vocal_start)))
                add(target, beat, 70, f"同名LRCの最初の歌詞タイムスタンプ {vocal_start:.3f}秒を最寄りの拍へ合わせた候補。歌声検出ではありません。", aligned=False)
            else:
                verses = [s for s in sections if s.kind == "VERSE"]
                if verses:
                    beat = verses[0].start_beat
                    add(target, beat, 30, "Vocalの開始位置は未取得です。rekordbox の最初の Verse を歌い始めの仮候補として表示しています。歌声は検出していないため、試聴して必ず修正・確認してください。", aligned=False)
                    warnings.append("歌い始めは Verse 先頭の仮候補です。歌声の自動検出ではありません。")
        if len(out) == before:
            warnings.append(f"{TARGET_LABELS.get(target, target)}：位置を特定できず、候補を生成しませんでした。試聴して位置を指定できます。")
    return out, list(dict.fromkeys(warnings))
