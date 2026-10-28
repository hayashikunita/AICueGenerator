// キュー種別ごとの表示メタ情報（色・ラベル・アイコン）。

export interface CueMeta {
  label: string;
  color: string;
  glow: string;
  icon: string;
}

interface CueBase {
  label: string;
  color: string;
  icon: string;
}

// 凡例・設定での表示順。
export const CUE_ORDER = ["INTRO_END", "BUILD", "DROP", "BREAK", "OUTRO", "OUTRO_END", "INTRO_START", "CHORUS_START", "CHORUS_END", "CHORUS_END_MINUS_8_BARS", "VOCAL_START", "VOCAL_END", "INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3", "INTRO_INTERVAL", "INTRO_END_BEFORE", "OUTRO_INTERVAL", "OUTRO_END_BEFORE", "FADE_END", "FADE_END_BEFORE", "TRACK_END", "TRACK_END_BEFORE"] as const;

const CUES: Record<string, CueBase> = {
  INTRO_BAR: { label: "イントロの指定小節目", color: "#5b8cff", icon: "▸" },
  INTRO_BAR_X2: { label: "イントロの指定小節目×2", color: "#5b8cff", icon: "▸" },
  INTRO_BAR_X3: { label: "イントロの指定小節目×3", color: "#5b8cff", icon: "▸" },
  INTRO_START: { label: "イントロの始まり", color: "#5b8cff", icon: "▶" },
  CHORUS_START: { label: "サビの始まり", color: "#ff5d73", icon: "♫" },
  CHORUS_END: { label: "サビの終わり", color: "#e6b23a", icon: "■" },
  CHORUS_END_MINUS_8_BARS: { label: "サビ終わり8小節前", color: "#9a7cff", icon: "↤" },
  VOCAL_START: { label: "歌い始め（要確認）", color: "#3fb6c9", icon: "♪" },
  VOCAL_END: { label: "ボーカルの終わり（要確認）", color: "#3fb6c9", icon: "■" },
  INTRO_END: { label: "イントロの終わり", color: "#5b8cff", icon: "▶" },
  OUTRO_END: { label: "アウトロの終わり", color: "#9a7cff", icon: "■" },
  INTRO_INTERVAL: { label: "イントロ開始からの小節間隔", color: "#5b8cff", icon: "▸" },
  INTRO_END_BEFORE: { label: "イントロの終わりの手前", color: "#5b8cff", icon: "↤" },
  OUTRO_INTERVAL: { label: "アウトロ内の小節間隔", color: "#9a7cff", icon: "▸" },
  OUTRO_END_BEFORE: { label: "アウトロの終わりの手前", color: "#9a7cff", icon: "↤" },
  FADE_END: { label: "音量が小さくなる終わり", color: "#3fb6c9", icon: "◁" },
  FADE_END_BEFORE: { label: "音量が小さくなる終わりの手前", color: "#3fb6c9", icon: "↤" },
  TRACK_END: { label: "曲の終わり", color: "#9aa2b1", icon: "■" },
  TRACK_END_BEFORE: { label: "曲の終わりの手前", color: "#9aa2b1", icon: "↤" },
  BUILD: { label: "Build", color: "#e6b23a", icon: "↗" },
  DROP: { label: "Drop", color: "#ff5d73", icon: "⚡" },
  BREAK: { label: "Break", color: "#3fb6c9", icon: "▽" },
  OUTRO: { label: "Outro", color: "#9a7cff", icon: "■" },
};

const FALLBACK: CueBase = { label: "Cue", color: "#9aa2b1", icon: "◆" };

function cueBase(type: string): CueBase {
  return CUES[type] ?? FALLBACK;
}

export function defaultCueColor(type: string): string {
  return cueBase(type).color;
}

// 色から発光用の rgba を導出する。
export function glowFrom(color: string, alpha = 0.45): string {
  const hex = color.replace("#", "");
  const full =
    hex.length === 3
      ? hex
          .split("")
          .map((c) => c + c)
          .join("")
      : hex;
  const n = Number.parseInt(full, 16);
  if (Number.isNaN(n) || full.length !== 6) return `rgba(154, 162, 177, ${alpha})`;
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// colors: 種別→色 の上書きマップ（任意）。未指定なら既定色を使う。
export function cueMeta(type: string, colors?: Record<string, string>): CueMeta {
  const base = cueBase(type);
  const color = colors?.[type] ?? base.color;
  return { label: base.label, color, glow: glowFrom(color), icon: base.icon };
}

export function fmtTime(ms: number): string {
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}
