import type { CueKind, CuePreset } from "./types";

export function presetColor(preset: CuePreset | null | undefined, kind: "MEMORY" | "HOT", fallback: string): string {
  return preset ? (kind === "MEMORY" ? preset.memory_color ?? "#9a9a9a" : preset.hot_color) : fallback;
}

export function presetBackground(preset: CuePreset | null | undefined, kind: CueKind, fallback: (kind: CueKind) => string): string {
  if (!preset) return fallback(kind);
  const memory = presetColor(preset, "MEMORY", "#00ffff");
  const hot = presetColor(preset, "HOT", "#ff5d73");
  return kind === "BOTH" ? `linear-gradient(90deg, ${memory} 0%, ${memory} 50%, ${hot} 50%, ${hot} 100%)` : kind === "MEMORY" ? memory : hot;
}

export interface CuePreferences { common: CuePreset | null; targets: Record<string, CuePreset>; endBars: 1 | 4 | 8 | 16 }
export const CUE_PREFERENCES_KEY = "aicue.cuePresets";
export function loadCuePreferences(): CuePreferences {
  const fallback: CuePreferences = { common: null, targets: {}, endBars: 8 };
  const valid = (value: unknown): value is CuePreset => {
    if (!value || typeof value !== "object") return false;
    const p = value as CuePreset;
    return ["MEMORY", "HOT", "BOTH"].includes(p.cue_kind) && (p.memory_color === null || /^#[0-9a-f]{6}$/i.test(p.memory_color)) && /^#[0-9a-f]{6}$/i.test(p.hot_color);
  };
  try {
    const saved = JSON.parse(localStorage.getItem(CUE_PREFERENCES_KEY) ?? "null");
    if (!saved || typeof saved !== "object") return fallback;
    return { common: valid(saved.common) ? saved.common : null, targets: Object.fromEntries(Object.entries(saved.targets ?? {}).filter(([, value]) => valid(value))) as Record<string, CuePreset>, endBars: [1, 4, 8, 16].includes(saved.endBars) ? saved.endBars : 8 };
  } catch { return fallback; }
}
