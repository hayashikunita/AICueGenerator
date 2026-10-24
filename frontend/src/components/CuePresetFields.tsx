import type { CueKind, CuePreset } from "../types";
import { MemoryCuePalette } from "./MemoryCuePalette";

export function CuePresetFields({ value, onChange, label }: { value: CuePreset; onChange: (value: CuePreset) => void; label: string }) {
  return <div className="cue-preset-fields">
    <label>Cueの種類<select aria-label={`${label}のCue種類`} value={value.cue_kind} onChange={(event) => onChange({ ...value, cue_kind: event.target.value as CueKind })}><option value="MEMORY">Memory Cue</option><option value="HOT">Hot Cue</option><option value="BOTH">両方</option></select></label>
    {value.cue_kind !== "HOT" && <div className="cue-preset-color"><span>Memory Cueの色</span><MemoryCuePalette label={`${label} Memory Cue の色`} value={value.memory_color ?? "NONE"} onChange={(color) => onChange({ ...value, memory_color: color === "NONE" ? null : color })} /></div>}
    {value.cue_kind !== "MEMORY" && <label className="cue-preset-color">Hot Cueの色<input type="color" aria-label={`${label} Hot Cue の色`} value={value.hot_color} onChange={(event) => onChange({ ...value, hot_color: event.target.value })} /></label>}
  </div>;
}
