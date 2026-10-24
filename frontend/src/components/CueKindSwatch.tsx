import type { CueKind, CuePreset } from "../types";
import { presetBackground } from "../cuePresets";
import { useCueColors } from "./CueColors";

export function CueKindSwatch({ kind, preset }: { kind: CueKind; preset?: CuePreset | null }) {
  const { kindBackground, kindValue } = useCueColors();
  const unset = kind === "MEMORY" && (preset ? preset.memory_color === null : kindValue("MEMORY") === "NONE");
  return <span className={`cue-kind-swatch${kind === "MEMORY" ? " memory" : ""}${unset ? " unset" : ""}`} style={{ background: unset ? "transparent" : presetBackground(preset, kind, kindBackground) }} aria-hidden="true" />;
}
