import type { CueKind } from "../types";
import { useCueColors } from "./CueColors";

export function CueKindSwatch({ kind }: { kind: CueKind }) {
  const { kindBackground } = useCueColors();
  return <span className="cue-kind-swatch" style={{ background: kindBackground(kind) }} aria-hidden="true" />;
}
