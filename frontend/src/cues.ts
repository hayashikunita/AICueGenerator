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
export const CUE_ORDER = ["INTRO_END", "BUILD", "DROP", "BREAK", "OUTRO"] as const;

const CUES: Record<string, CueBase> = {
  INTRO_END: { label: "Intro End", color: "#5b8cff", icon: "▶" },
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
