"""Intro/outro suggestions with optional vocal onset, using saved grid positions."""
from __future__ import annotations

import numpy as np

from ..domain.cue_targets import INTRO_OUTRO_TARGETS, INTRO_OUTRO_DEFAULT_TARGETS, cue_target_label
from ..domain.enums import CueType
from ..domain.models import BeatGrid, CueCandidate, Evidence, PhraseSection
from .activity import activity_bounds
from .cue_targets import target_candidates
from .features import BeatFeatures


def fade_end_beat(levels: np.ndarray) -> int | None:
    """Require a sustained decline before the audible end; a hard cut is not a fade."""
    audible = activity_bounds(levels)
    if audible is None or audible.end_beat - audible.start_beat < 8:
        return None
    values = np.asarray(levels, dtype=float)
    smooth = np.array([np.median(values[max(0, i - 1):i + 2]) for i in range(len(values))])
    end = audible.end_beat
    start = max(audible.start_beat, end - 128)
    # Search the last 32 bars. Ignore solitary trailing ticks via activity_bounds.
    peak = start + int(np.argmax(smooth[start:end]))
    tail = smooth[peak:end]
    if len(tail) < 8 or tail[0] < 1e-4:
        return None
    decibels = 20 * np.log10(np.maximum(tail, 1e-8))
    drops = np.diff(decibels)
    if decibels[0] - float(np.median(decibels[-3:])) < 12 or np.count_nonzero(drops < -.15) < 3:
        return None
    if np.count_nonzero(drops <= .5) / len(drops) < .65:
        return None
    return end


def intro_outro_candidates(feat: BeatFeatures, grid: BeatGrid, base: list[CueCandidate],
                           sections: tuple[PhraseSection, ...], config: dict, duration: float,
                           *, vocal_start: float | None = None, vocal_start_source: str = "LRC", vocal_end: float | None = None) -> tuple[list[CueCandidate], list[str]]:
    selected = list(dict.fromkeys(config.get("targets", INTRO_OUTRO_DEFAULT_TARGETS)))
    if not selected or any(target not in INTRO_OUTRO_TARGETS for target in selected):
        raise ValueError("イントロアウトロ特化の対象を選んでください。")
    settings = {name: config.get(name, 8) for name in ("intro_position_bars", "intro_interval_bars", "intro_before_bars", "outro_interval_bars", "outro_before_bars", "fade_before_bars", "track_before_bars")}
    if any(not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 128 for value in settings.values()):
        raise ValueError("小節数は1〜128の整数で指定してください。")
    config = {**config, **settings}
    bars = np.array(grid.downbeat_indices, dtype=int)
    times = np.array(grid.beat_times)
    if not len(bars):
        return [], ["小節頭がないため、イントロアウトロ特化の候補を生成できませんでした。"]
    # Only intro/outro targets are evaluated, even when other phrase labels exist.
    anchors, _ = target_candidates(feat, grid, base, ["INTRO_START", "INTRO_END", "OUTRO", "OUTRO_END"],
                                                tuple(s for s in sections if s.kind in {"INTRO", "OUTRO"}), top_k=1, end_alignment_bars=1)
    points = {candidate.cue_type.value: candidate for candidate in anchors}
    result: list[CueCandidate] = []
    warnings: list[str] = []

    def label(target):
        return cue_target_label(target, {"intro_outro": config})

    def add(target, beat, confidence, detail):
        if 0 <= beat < len(times) and times[beat] < duration:
            result.append(CueCandidate(CueType(target), float(times[beat]), int(beat), confidence,
                                       1 + sum(c.cue_type.value == target for c in result),
                                       (Evidence("候補の位置と根拠", 100, confidence / 100, label(target) + "。" + detail),), True))

    def index(target):
        point = points.get(target)
        return int(np.searchsorted(bars, point.beat_index)) if point is not None else None

    def floor_bar(beat):
        candidates = bars[(bars <= beat) & (times[bars] < duration)]
        return int(candidates[-1]) if len(candidates) else None

    last = floor_bar(len(times) - 1)
    fade = fade_end_beat(feat.rms) if any(t.startswith("FADE_") for t in selected) else None
    fade_bar = floor_bar(fade) if fade is not None else None
    for target in selected:
        count_before = len(result)
        if target in {"VOCAL_START", "VOCAL_END"}:
            vocal_candidates, _ = target_candidates(feat, grid, [], [target], (), top_k=1,
                vocal_start=vocal_start, vocal_start_source=vocal_start_source, vocal_end=vocal_end, allow_vocal_fallback=False)
            result.extend(c for c in vocal_candidates if c.time_sec < duration)
        elif target in {"INTRO_START", "INTRO_END", "OUTRO", "OUTRO_END"}:
            point = points.get(target)
            if point:
                add(target, point.beat_index, point.confidence, point.evidence[0].detail)
        elif target in {"INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3"}:
            start, end = index("INTRO_START"), index("INTRO_END")
            multiplier = {"INTRO_BAR": 1, "INTRO_BAR_X2": 2, "INTRO_BAR_X3": 3}[target]
            ordinal = settings["intro_position_bars"] * multiplier
            # The first bar is the intro start. Never include the next section's first bar.
            bar = start + ordinal - 1 if start is not None else None
            if bar is not None and end is not None and start <= bar < end:
                confidence = min(points["INTRO_START"].confidence, points["INTRO_END"].confidence)
                add(target, int(bars[bar]), confidence, f"イントロの最初の小節を1小節目として数えた{ordinal}小節目の保存済み小節頭。イントロの終わりは含めません。")
        elif target in {"INTRO_INTERVAL", "OUTRO_INTERVAL"}:
            intro = target == "INTRO_INTERVAL"
            start, end = index("INTRO_START" if intro else "OUTRO"), index("INTRO_END" if intro else "OUTRO_END")
            if start is not None and end is not None and start < end:
                step = settings["intro_interval_bars" if intro else "outro_interval_bars"]
                confidence = min(points["INTRO_START" if intro else "OUTRO"].confidence, points["INTRO_END" if intro else "OUTRO_END"].confidence)
                for bar in range(start + step, end, step):
                    if len(result) >= 1000:
                        warnings.append("1曲の候補数が1000件に達したため間隔候補を省略しました。小節間隔を広げてください。")
                        break
                    add(target, int(bars[bar]), confidence, f"区間の始まりから{step}小節ずつ数えた保存済みの小節頭。")
        elif target in {"INTRO_END_BEFORE", "OUTRO_END_BEFORE", "FADE_END_BEFORE", "TRACK_END_BEFORE"}:
            if target == "INTRO_END_BEFORE":
                end, lower, amount, confidence = index("INTRO_END"), index("INTRO_START"), settings["intro_before_bars"], points.get("INTRO_END").confidence if points.get("INTRO_END") else 0
            elif target == "OUTRO_END_BEFORE":
                end, lower, amount, confidence = index("OUTRO_END"), index("OUTRO"), settings["outro_before_bars"], points.get("OUTRO_END").confidence if points.get("OUTRO_END") else 0
            else:
                endpoint = fade_bar if target == "FADE_END_BEFORE" else last
                end = int(np.searchsorted(bars, endpoint)) if endpoint is not None else None
                lower, amount, confidence = 0, settings["fade_before_bars" if target == "FADE_END_BEFORE" else "track_before_bars"], 55 if target == "FADE_END_BEFORE" else 85
            if end is not None and lower is not None and end - amount >= lower:
                add(target, int(bars[end - amount]), confidence, f"基準の終わりから保存済みの小節頭を{amount}小節戻しています。固定秒数では計算しません。")
        elif target == "FADE_END" and fade_bar is not None:
            add(target, fade_bar, 55, "曲末の継続する音量低下から推定し、音がほぼ聞こえなくなる位置以前の小節頭へ合わせています。")
        elif target == "TRACK_END" and last is not None:
            add(target, last, 85, f"音源ファイルの末尾{duration:.3f}秒より前にある最後の保存済み小節頭。末尾に新しい拍は作りません。")
        if len(result) == count_before:
            if target == "VOCAL_END":
                warnings.append("ボーカルの終わり：曲末までの分離結果から継続する声の終わりを確認できず、省略しました。AI補助を利用し、試聴で確認してください。LRCの最終行やVerse末尾では代用しません。")
                continue
            if target == "VOCAL_START":
                warnings.append("歌い始め：継続する声の開始や歌詞時刻を確認できなかったため省略しました。AI補助または同名LRCを利用し、試聴で確認してください。Verse先頭の置き換えは行いません。")
                continue
            reason = "フェード終端を確認できませんでした（急に音が切れる曲では生成しません）" if target.startswith("FADE_") and fade is None else "区間の境界や指定小節数に合う位置がありません。小節数を減らすか、試聴して補ってください"
            warnings.append(f"{label(target)}：{reason}。")
    return result, list(dict.fromkeys(warnings))
