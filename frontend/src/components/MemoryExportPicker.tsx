import type { Candidate } from "../types";
import { CUE_LIMITS } from "../cueKinds";
import { CueKindSwatch } from "./CueKindSwatch";
import { fmtTime } from "../cues";
import { useCueMeta } from "./CueColors";

export function highestConfidenceMemory(candidates: Candidate[]): string[] {
  const groups = new Map<string, Candidate[]>();
  for (const candidate of candidates) if (candidate.accepted && (candidate.cue_kind === "MEMORY" || candidate.cue_kind === "BOTH")) {
    const key = candidate.track_id ?? "single";
    groups.set(key, [...(groups.get(key) ?? []), candidate]);
  }
  return Array.from(groups.values()).flatMap((group) => [...group].sort((a, b) => b.confidence - a.confidence || a.rank - b.rank || a.time_ms - b.time_ms || a.id.localeCompare(b.id)).slice(0, CUE_LIMITS.MEMORY).map((candidate) => candidate.id));
}

export function MemoryExportPicker({ candidates, selectedIds, trackNames, onChange, disabled, onAudition }: {
  candidates: Candidate[];
  selectedIds: string[];
  trackNames: Record<string, string>;
  onChange: (ids: string[]) => void;
  disabled: boolean;
  onAudition?: (timeMs: number, trackId?: string | null) => void;
}) {
  const meta = useCueMeta();
  const groups = new Map<string, Candidate[]>();
  for (const candidate of candidates) if (candidate.accepted && (candidate.cue_kind === "MEMORY" || candidate.cue_kind === "BOTH")) {
    const key = candidate.track_id ?? "single";
    groups.set(key, [...(groups.get(key) ?? []), candidate]);
  }
  const hasOverflow = Array.from(groups.values()).some((group) => group.length > CUE_LIMITS.MEMORY);
  if (!groups.size) return null;
  return <details className="memory-export-picker" open={hasOverflow ? true : undefined}>
    <summary>XMLに書き出すMemory Cueを確認（{selectedIds.length}件）</summary>
    <p className="field-help">曲ごとに信頼度の高い{CUE_LIMITS.MEMORY}件までを自動選択しています。同じ信頼度なら候補順位・時刻順で選びます。チェックを外して別の候補へ入れ替えられます。候補・採用状態は変更しません。</p>
    {Array.from(groups, ([trackId, group]) => {
      const selectedCount = group.filter((candidate) => selectedIds.includes(candidate.id)).length;
      const ordered = [...group].sort((a, b) => a.time_ms - b.time_ms || a.id.localeCompare(b.id));
      return <div className="memory-export-track" key={trackId}>
        <strong>{trackNames[trackId] ?? "選択中の曲"}</strong>
        <p className="field-help">採用 {group.length}件 → 今回のXML {selectedCount}/{CUE_LIMITS.MEMORY}件{group.length > selectedCount ? `（${group.length - selectedCount}件はアプリ内に保持）` : ""}</p>
        <div className="row"><button type="button" className="secondary tiny" disabled={disabled} onClick={() => { const ownIds = new Set(group.map((candidate) => candidate.id)); onChange([...selectedIds.filter((id) => !ownIds.has(id)), ...highestConfidenceMemory(group)]); }}>信頼度順で選び直す</button><button type="button" className="secondary tiny" disabled={disabled} onClick={() => { const ownIds = new Set(group.map((candidate) => candidate.id)); onChange(selectedIds.filter((id) => !ownIds.has(id))); }}>この曲の出力選択を解除</button></div>
        <div className="memory-export-rows" aria-label={`${trackNames[trackId] ?? "選択中の曲"}のMemory Cue書き出し候補`}>
          {ordered.map((candidate) => <div className="memory-export-row" key={candidate.id}>
            <CueKindSwatch kind="MEMORY" preset={candidate.preset} />
            <label><input type="checkbox" checked={selectedIds.includes(candidate.id)} disabled={disabled || (!selectedIds.includes(candidate.id) && selectedCount >= CUE_LIMITS.MEMORY)} onChange={(event) => onChange(event.target.checked ? [...selectedIds, candidate.id] : selectedIds.filter((id) => id !== candidate.id))} /><span><span className="mono">{fmtTime(candidate.time_ms)}</span> {candidate.display_label ?? meta(candidate.type).label}<small>信頼度 {candidate.confidence}</small></span></label>
            {onAudition && <button type="button" className="secondary tiny" disabled={disabled} onClick={() => onAudition(candidate.time_ms, candidate.track_id)}>試聴</button>}
          </div>)}
        </div>
      </div>;
    })}
  </details>;
}
