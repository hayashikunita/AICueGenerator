import type { CueKind } from "./types";

export const SINGLE_CUE_KINDS = ["MEMORY", "HOT"] as const;
export type SingleCueKind = typeof SINGLE_CUE_KINDS[number];
export const CUE_LIMITS = { MEMORY: 10, HOT: 8 } as const;

export const DEFAULT_KIND_COLORS: Record<SingleCueKind, string> = {
  MEMORY: "#00ffff",
  HOT: "#ff5d73",
};

// Keep button labels readable even when a user chooses very dark/light colors.
export function colorText(color: string): string {
  const channels = [1, 3, 5].map((offset) => {
    const value = parseInt(color.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const luminance = channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  return luminance > 0.179 ? "#10131b" : "#ffffff";
}

export const CUE_KIND_LABEL: Record<CueKind, string> = {
  MEMORY: "Memory Cue",
  HOT: "Hot Cue",
  BOTH: "Memory Cue + Hot Cue",
};
