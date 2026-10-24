"""Purpose-specific suggestions, keeping source labels and uncertainty explicit."""
from __future__ import annotations

import re

import numpy as np

from ..domain.enums import CueType
from ..domain.models import BeatGrid, CueCandidate, Evidence, PhraseSection
from ..domain.cue_targets import CUE_TARGET_LABELS as TARGET_LABELS
from .features import BeatFeatures
from .activity import activity_bounds

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
    *, top_k: int = 3, vocal_start: float | None = None, end_alignment_bars: int = 1,
    vocal_start_source: str = "LRC", repetition_scores: np.ndarray | None = None,
    allow_vocal_fallback: bool = True,
) -> tuple[list[CueCandidate], list[str]]:
    times = np.asarray(grid.beat_times)
    bars = np.asarray(grid.downbeat_indices, dtype=int)
    out: list[CueCandidate] = []
    warnings: list[str] = []
    audible = activity_bounds(feat.rms)
    if not len(bars):
        return [], ["小節頭がないため、指定位置の候補を生成できませんでした。"]
    if end_alignment_bars not in (1, 4, 8, 16):
        raise ValueError("終わりの位置は1・4・8・16小節から選んでください。")

    def bar_index(beat: int) -> int | None:
        if not 0 <= beat < len(times):
            return None
        return int(np.argmin(np.abs(bars - beat)))

    def add(target: str, beat: int, confidence: float, detail: str, *, aligned=True):
        if (0 <= beat < len(times) and sum(c.cue_type.value == target for c in out) < top_k
                and not any(c.cue_type.value == target and c.beat_index == beat for c in out)):
            out.append(CueCandidate(CueType(target), float(times[beat]), int(beat), confidence,
                                    1 + sum(c.cue_type.value == target for c in out),
                                    (Evidence("候補の位置と根拠", 100, confidence / 100, detail),), aligned))

    def add_end(target: str, start: int, end: int, confidence: float, detail: str):
        # Count actual bars from the first downbeat, including tempo changes.
        # Never invent a beat beyond the saved grid or extend into a new section.
        choices = bars[(np.arange(len(bars)) % end_alignment_bars == 0) & (bars > start) & (bars <= end)]
        if len(choices):
            beat = int(choices[-1])
            add(target, beat, confidence, detail + f"。最初の小節頭を起点に{end_alignment_bars}小節単位で、区間末尾以前の小節頭へ合わせています。")
        else:
            warnings.append(f"{TARGET_LABELS[target]}：区間内に{end_alignment_bars}小節単位の区切りがないため候補を省略しました。1小節など、短い単位に変更して再解析できます。")

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
                    repetition = float(repetition_scores[start_bar]) if repetition_scores is not None else 0
                    detail = "音量・低域の変化から推定した Drop〜Break/Outro の区間。サビとは限らないため試聴で確認してください。"
                    if repetition_scores is not None:
                        detail += "音色・和音の繰り返しも照合しています。" if repetition >= .5 else "離れた区間との繰り返しを十分確認できないため、信頼度を下げています。"
                    choruses.append((start_bar, end_bar, min(50 if repetition >= .5 else 35, drop.confidence), detail))
        if repetition_scores is not None:
            choruses.sort(key=lambda section: (-repetition_scores[section[0]], -section[2], section[0]))

    for target in dict.fromkeys(targets):
        before = len(out)
        if target == "INTRO_START":
            intros = [s for s in sections if s.kind == "INTRO"]
            if intros and audible:
                section = intros[0]
                choices = bars[(bars >= max(section.start_beat, audible.start_beat)) & (bars < min(section.end_beat, audible.end_beat))]
                if len(choices):
                    shifted = "。曲頭の無音・孤立した音を除き、継続する有音部分以降の小節頭へ合わせています" if choices[0] > section.start_beat else ""
                    add(target, int(choices[0]), 85, "rekordbox の Intro フレーズの先頭" + shifted)
            elif not intros and audible:
                choices = bars[(bars >= audible.start_beat) & (bars < audible.end_beat)]
                if len(choices):
                    add(target, int(choices[0]), 50, "継続する有音部分以降の小節頭。曲頭の無音・孤立した音を除外し、静かな導入部も確認しています。Intro ラベルがないため推定です。")
        elif target in {"INTRO_END", "OUTRO_END"}:
            kind = "INTRO" if target == "INTRO_END" else "OUTRO"
            matches = [s for s in sections if s.kind == kind]
            if matches and audible:
                section = matches[0] if kind == "INTRO" else matches[-1]
                end = min(section.end_beat, audible.end_beat, len(times) - 1)
                detail = f"rekordbox の {kind.title()} フレーズの終わり"
                if end < section.end_beat:
                    detail += "。末尾の無音・孤立した音を除き、継続する有音部分の末尾までに制限しています"
                add_end(target, max(section.start_beat, audible.start_beat), end, 85, detail)
            elif not matches and target == "INTRO_END" and audible:
                for candidate in sorted((c for c in base if c.cue_type == CueType.INTRO_END), key=lambda c: (-c.confidence, c.rank, c.time_sec)):
                    if audible.start_beat < candidate.beat_index < audible.end_beat:
                        add_end(target, max(int(bars[0]) - 1, audible.start_beat), candidate.beat_index, min(50, candidate.confidence), "Introラベルがないため、音源の展開から推定したイントロ終端。信頼度順で候補を表示しています")
            elif not matches and target == "OUTRO_END" and audible:
                starts = [c.beat_index for c in base if c.cue_type == CueType.OUTRO and c.beat_index < audible.end_beat]
                add_end(target, max(starts) if starts else max(int(bars[0]) - 1, audible.start_beat), min(audible.end_beat, len(times) - 1), 40, "Outroラベルがないため、継続する有音部分の末尾から推定した曲末直前の区切り。静かなフェードを含め、末尾の孤立した音は除外しています")
        elif target == "OUTRO":
            outros = [s for s in sections if s.kind == "OUTRO"]
            if outros and audible:
                section = outros[-1]
                choices = bars[(bars >= max(section.start_beat, audible.start_beat)) & (bars < min(section.end_beat, audible.end_beat))]
                if len(choices):
                    add(target, int(choices[0]), 85, "rekordbox の Outro フレーズの先頭")
            elif not outros and audible:
                for candidate in sorted((c for c in base if c.cue_type == CueType.OUTRO), key=lambda c: (-c.confidence, c.rank, c.time_sec)):
                    if audible.start_beat <= candidate.beat_index < audible.end_beat:
                        add(target, candidate.beat_index, min(50, candidate.confidence), "Outroラベルがないため、音源の展開から推定したアウトロ先頭。信頼度順で候補を表示しています")
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
                if vocal_start_source.startswith("DEMUCS"):
                    detail = f"HTDemucsで分離したボーカル成分から、短い単発音と弱い分離漏れを除き、継続する声の開始 {vocal_start:.3f}秒を最寄りの拍 {times[beat]:.3f}秒へ合わせた候補（差 {times[beat] - vocal_start:+.3f}秒）。歌詞認識ではなく、長い掛け声・話し声を含む可能性があるため試聴してください。"
                    add(target, beat, 65, detail, aligned=False)
                else:
                    add(target, beat, 70, f"同名LRCの最初の歌詞タイムスタンプ {vocal_start:.3f}秒を最寄りの拍へ合わせた候補。歌声検出ではありません。", aligned=False)
            elif allow_vocal_fallback:
                verses = [s for s in sections if s.kind == "VERSE"]
                if verses:
                    beat = verses[0].start_beat
                    add(target, beat, 30, "Vocalの開始位置は未取得です。rekordbox の最初の Verse を歌い始めの仮候補として表示しています。歌声は検出していないため、試聴して必ず修正・確認してください。", aligned=False)
                    warnings.append("歌い始めは Verse 先頭の仮候補です。歌声の自動検出ではありません。")
        if len(out) == before and not any(warning.startswith(f"{TARGET_LABELS.get(target, target)}：") for warning in warnings):
            warnings.append(f"{TARGET_LABELS.get(target, target)}：位置を特定できず、候補を生成しませんでした。試聴して位置を指定できます。")
    return out, list(dict.fromkeys(warnings))
