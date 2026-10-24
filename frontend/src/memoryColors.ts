// The eight named choices shown in the user's rekordbox Memory Cue menu.
export const MEMORY_CUE_COLORS = [
  { label: "桃", value: "#ff66ff" },
  { label: "赤", value: "#ff0000" },
  { label: "橙", value: "#ff9900" },
  { label: "黄", value: "#ffff00" },
  { label: "緑", value: "#00ff00" },
  { label: "水", value: "#00ffff" },
  { label: "青", value: "#0000ff" },
  { label: "紫", value: "#9900ff" },
  { label: "未設定", value: "NONE" },
] as const;

export function memoryColorLabel(value: string): string {
  return MEMORY_CUE_COLORS.find((color) => color.value === value.toLowerCase() || color.value === value)?.label ?? `以前の設定 (${value})`;
}
