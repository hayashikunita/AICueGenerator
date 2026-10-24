import type { CueTarget } from "./types";

export const CUE_TARGETS: { value: CueTarget; label: string }[] = [
  { value: "INTRO_START", label: "イントロの始まり" },
  { value: "OUTRO", label: "アウトロの始まり" },
  { value: "CHORUS_START", label: "サビの始まり" },
  { value: "CHORUS_END", label: "サビの終わり" },
  { value: "CHORUS_END_MINUS_8_BARS", label: "サビの終わりから8小節前" },
  { value: "VOCAL_START", label: "歌い始め" },
];
