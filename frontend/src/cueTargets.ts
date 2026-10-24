import type { CueTarget } from "./types";
import { INTRO_OUTRO_TARGETS } from "./introOutro";

export const CUE_TARGETS: { value: CueTarget; label: string }[] = [
  { value: "INTRO_START", label: "イントロの始まり" },
  { value: "INTRO_END", label: "イントロの終わり" },
  { value: "OUTRO", label: "アウトロの始まり" },
  { value: "OUTRO_END", label: "アウトロの終わり" },
  { value: "CHORUS_START", label: "サビの始まり" },
  { value: "CHORUS_END", label: "サビの終わり" },
  { value: "CHORUS_END_MINUS_8_BARS", label: "サビの終わりから8小節前" },
  { value: "VOCAL_START", label: "歌い始め" },
];

export const ALL_CUE_TARGETS = [...CUE_TARGETS, ...INTRO_OUTRO_TARGETS.filter((option) => !CUE_TARGETS.some((target) => target.value === option.value))];
