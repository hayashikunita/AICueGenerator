import type { CueTarget, IntroOutroSettings } from "./types";

export type BarField = Exclude<keyof IntroOutroSettings, "targets">;
export const BAR_FIELDS: BarField[] = ["intro_position_bars", "intro_interval_bars", "intro_before_bars", "outro_interval_bars", "outro_before_bars", "fade_before_bars", "track_before_bars"];
export const INTRO_OUTRO_GROUPS: { label: string; targets: { value: CueTarget; label: string; field?: BarField; template?: string; multiplier?: number }[] }[] = [
  { label: "イントロ", targets: [
    { value: "INTRO_START", label: "イントロの始まり" },
    { value: "INTRO_BAR", label: "イントロの指定小節目", field: "intro_position_bars", template: "イントロの{n}小節目", multiplier: 1 },
    { value: "INTRO_BAR_X2", label: "イントロの指定小節目×2", field: "intro_position_bars", template: "イントロの{n}小節目", multiplier: 2 },
    { value: "INTRO_BAR_X3", label: "イントロの指定小節目×3", field: "intro_position_bars", template: "イントロの{n}小節目", multiplier: 3 },
    { value: "INTRO_INTERVAL", label: "イントロ間の小節ごと", field: "intro_interval_bars", template: "イントロ間の{n}小節ごと" },
    { value: "INTRO_END_BEFORE", label: "イントロの終わりの手前", field: "intro_before_bars", template: "イントロの終わりから{n}小節前" },
    { value: "INTRO_END", label: "イントロの終わり" },
  ] },
  { label: "アウトロ", targets: [
    { value: "OUTRO", label: "アウトロの始まり" },
    { value: "OUTRO_INTERVAL", label: "アウトロ間の小節ごと", field: "outro_interval_bars", template: "アウトロ間の{n}小節ごと" },
    { value: "OUTRO_END_BEFORE", label: "アウトロの終わりの手前", field: "outro_before_bars", template: "アウトロの終わりから{n}小節前" },
    { value: "OUTRO_END", label: "アウトロの終わり" },
  ] },
  { label: "ボーカル", targets: [
    { value: "VOCAL_START", label: "歌い始め" },
  ] },
  { label: "フェードの終わり", targets: [
    { value: "FADE_END_BEFORE", label: "曲の音量が小さくなる終わりの手前", field: "fade_before_bars", template: "曲の音量が小さくなる終わりから{n}小節前" },
    { value: "FADE_END", label: "曲の音量が小さくなる終わり" },
  ] },
  { label: "曲の終わり", targets: [
    { value: "TRACK_END_BEFORE", label: "曲の終わりの手前", field: "track_before_bars", template: "曲の終わりから{n}小節前" },
    { value: "TRACK_END", label: "曲の終わり" },
  ] },
];
export const INTRO_OUTRO_TARGETS = INTRO_OUTRO_GROUPS.flatMap((group) => group.targets);
export const INTRO_OUTRO_KEY = "aicue.introOutro";
export function defaultIntroOutro(): IntroOutroSettings {
  return { targets: INTRO_OUTRO_TARGETS.filter((target) => target.value !== "VOCAL_START").map((target) => target.value), intro_position_bars: 8, intro_interval_bars: 8, intro_before_bars: 8, outro_interval_bars: 8, outro_before_bars: 8, fade_before_bars: 8, track_before_bars: 8 };
}
export function introOutroLabel(target: CueTarget, value: IntroOutroSettings): string {
  const option = INTRO_OUTRO_TARGETS.find((item) => item.value === target);
  return option?.field && option.template ? option.template.replace("{n}", String((value[option.field] ?? 8) * (option.multiplier ?? 1))) : option?.label ?? target;
}
export function loadIntroOutro(): IntroOutroSettings {
  const value = defaultIntroOutro();
  try {
    const saved = JSON.parse(localStorage.getItem(INTRO_OUTRO_KEY) ?? "null");
    if (!saved || typeof saved !== "object") return value;
    if (Array.isArray(saved.targets)) value.targets = INTRO_OUTRO_TARGETS.filter((option) => saved.targets.includes(option.value)).map((option) => option.value);
    for (const field of BAR_FIELDS) if (Number.isInteger(saved[field]) && saved[field] >= 1 && saved[field] <= 128) value[field] = saved[field];
  } catch { /* Defaults remain usable. */ }
  return value;
}
