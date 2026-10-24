import { useState } from "react";
import type { Candidate } from "../types";
import { useCueColors, useCueMeta } from "./CueColors";
import { CueKindSwatch } from "./CueKindSwatch";

function preciseTime(ms: number) {
  const time = Math.max(0, Math.round(ms));
  return `${String(Math.floor(time / 60000)).padStart(2, "0")}:${String(Math.floor(time / 1000) % 60).padStart(2, "0")}:${String(time % 1000).padStart(3, "0")}`;
}

export function CueDock({ candidates, onAudition }: { candidates: Candidate[]; onAudition?: (candidate: Candidate) => void }) {
  const [kind, setKind] = useState<"MEMORY" | "HOT">("MEMORY");
  const [showCandidates, setShowCandidates] = useState(true);
  const meta = useCueMeta();
  const { kindValue } = useCueColors();
  const accepted = candidates.filter((c) => c.accepted === true && ((c.cue_kind ?? "MEMORY") === kind || c.cue_kind === "BOTH"));
  const pending = candidates.filter((c) => c.accepted == null);
  const rows = [...accepted, ...(showCandidates ? pending : [])].sort((a, b) => a.time_ms - b.time_ms);
  return <aside className="cue-dock" aria-label="Cueと候補の時刻一覧">
    <div className="cue-dock-heading">CUE / LOOP <span>採用 {accepted.length}</span></div>
    <label className="cue-dock-filter"><input type="checkbox" checked={showCandidates} onChange={(event) => setShowCandidates(event.currentTarget.checked)} />未採用の候補も表示（{pending.length}）</label>
    <div className="cue-dock-rows" aria-live="polite">
      {rows.map((candidate) => <button type="button" className="cue-dock-row" data-state={candidate.accepted ? "accepted" : "candidate"} key={candidate.id} disabled={!onAudition} onClick={() => onAudition?.(candidate)} aria-label={`${candidate.accepted ? kind === "MEMORY" ? "Memory Cue" : "Hot Cue" : "未採用候補"} ${meta(candidate.type).label} ${preciseTime(candidate.time_ms)}を試聴`}>
        {candidate.accepted || candidate.preset ? <CueKindSwatch kind={candidate.accepted ? kind : candidate.preset!.cue_kind} preset={candidate.preset} /> : <span className="cue-dock-pending-mark" aria-hidden="true">◇</span>}<time>{preciseTime(candidate.time_ms)}</time><span className="cue-dock-label">{candidate.display_label ?? meta(candidate.type).label}</span>
        {!candidate.accepted && <span className="cue-dock-pending-label">{candidate.preset ? `${candidate.preset.cue_kind === "HOT" ? "Hot" : candidate.preset.cue_kind === "BOTH" ? "両方" : "Memory"}候補` : "候補"}</span>}
      </button>)}
      {!rows.length && <p className="cue-dock-empty">{kind === "MEMORY" ? "Memory Cue" : "Hot Cue"}の採用済みCueはありません。{pending.length > 0 ? "「未採用の候補も表示」をオンにすると候補を確認できます。" : "下の候補一覧で採用すると、ここに時刻が並びます。"}</p>}
    </div>
    {showCandidates && pending.length > 0 && <p className="cue-dock-hint">{onAudition ? "候補はクリックで試聴。" : ""}下の候補一覧で採用できます。</p>}
    <div className="cue-dock-tabs" aria-label="Cue一覧の種類">
      <button type="button" aria-pressed={kind === "MEMORY"} onClick={() => setKind("MEMORY")}>MEMORY</button>
      <button type="button" aria-pressed={kind === "HOT"} onClick={() => setKind("HOT")}>HOT CUE</button>
    </div>
    {kind === "MEMORY" && rows.every((candidate) => candidate.preset ? candidate.preset.memory_color === null : kindValue("MEMORY") === "NONE") && (rows.length > 0 || kindValue("MEMORY") === "NONE") && <span className="cue-dock-note">色：未設定</span>}
  </aside>;
}
