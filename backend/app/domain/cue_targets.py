CUE_TARGET_LABELS = {
    "VOCAL_END": "ボーカルの終わり",
    "INTRO_BAR": "イントロの指定小節目", "INTRO_BAR_X2": "イントロの指定小節目×2", "INTRO_BAR_X3": "イントロの指定小節目×3",
    "INTRO_START": "イントロの始まり", "OUTRO": "アウトロの始まり",
    "INTRO_END": "イントロの終わり", "OUTRO_END": "アウトロの終わり",
    "CHORUS_START": "サビの始まり", "CHORUS_END": "サビの終わり",
    "CHORUS_END_MINUS_8_BARS": "サビの終わりから8小節前", "VOCAL_START": "歌い始め",
    "INTRO_INTERVAL": "イントロ内の小節間隔", "INTRO_END_BEFORE": "イントロの終わりの手前",
    "OUTRO_INTERVAL": "アウトロ内の小節間隔", "OUTRO_END_BEFORE": "アウトロの終わりの手前",
    "FADE_END": "曲の音量が小さくなる終わり", "FADE_END_BEFORE": "曲の音量が小さくなる終わりの手前",
    "TRACK_END": "曲の終わり", "TRACK_END_BEFORE": "曲の終わりの手前",
}

PURPOSE_TARGETS = ("INTRO_START", "OUTRO", "INTRO_END", "OUTRO_END", "CHORUS_START", "CHORUS_END", "CHORUS_END_MINUS_8_BARS", "VOCAL_START")

INTRO_OUTRO_TARGETS = (
    "INTRO_START", "INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3", "INTRO_INTERVAL", "INTRO_END_BEFORE", "INTRO_END",
    "OUTRO", "OUTRO_INTERVAL", "OUTRO_END_BEFORE", "OUTRO_END",
    "FADE_END_BEFORE", "FADE_END", "TRACK_END_BEFORE", "TRACK_END",
    "VOCAL_START", "VOCAL_END",
)
INTRO_OUTRO_DEFAULT_TARGETS = tuple(target for target in INTRO_OUTRO_TARGETS if target not in {"VOCAL_START", "VOCAL_END"})


def cue_target_label(target: str, params: dict | None = None) -> str:
    config = (params or {}).get("intro_outro") or {}
    if target in {"INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3"}:
        multiplier = {"INTRO_BAR": 1, "INTRO_BAR_X2": 2, "INTRO_BAR_X3": 3}[target]
        return f"イントロの{config.get('intro_position_bars', 8) * multiplier}小節目"
    formats = {
        "INTRO_INTERVAL": ("intro_interval_bars", "イントロ内の{}小節ごと"),
        "INTRO_END_BEFORE": ("intro_before_bars", "イントロの終わりから{}小節前"),
        "OUTRO_INTERVAL": ("outro_interval_bars", "アウトロ内の{}小節ごと"),
        "OUTRO_END_BEFORE": ("outro_before_bars", "アウトロの終わりから{}小節前"),
        "FADE_END_BEFORE": ("fade_before_bars", "曲の音量が小さくなる終わりから{}小節前"),
        "TRACK_END_BEFORE": ("track_before_bars", "曲の終わりから{}小節前"),
    }
    if target in formats:
        key, template = formats[target]
        return template.format(config.get(key, 8))
    return CUE_TARGET_LABELS.get(target, target)
