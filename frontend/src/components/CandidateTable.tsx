import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { fmtTime } from "../cues";
import type { Candidate, CueKind, CuePosition } from "../types";
import { CUE_KIND_LABEL, colorText } from "../cueKinds";
import { useCueColors, useCueMeta } from "./CueColors";
import { CueKindSwatch } from "./CueKindSwatch";
import { useToast } from "./Toast";

function Evidence({ c }: { c: Candidate }) {
  return (
    <div style={{ display: "grid", gap: 7, padding: "4px 2px" }}>
      {c.evidence.map((e) => {
        const pct = Math.round(e.score * 100);
        const band = pct >= 66 ? "high" : pct >= 40 ? "review" : "reject";
        return (
          <div key={e.name} className="row" style={{ gap: 10, flexWrap: "nowrap" }}>
            <span className="mono" style={{ minWidth: 130, fontSize: 12 }}>
              {e.name}
            </span>
            <div className="meter-wrap" style={{ flex: 1 }}>
              <div className={`meter ${band}`} style={{ flex: 1 }}>
                <span style={{ width: `${pct}%` }} />
              </div>
              <span className="meter-val">{pct}</span>
            </div>
            <span className="muted" style={{ fontSize: 11, minWidth: 60 }}>
              重み {e.weight}
            </span>
            {e.detail && <span className="muted" style={{ fontSize: 11 }}>{e.detail}</span>}
          </div>
        );
      })}
    </div>
  );
}

export function CandidateTable({
  candidates,
  onChanged,
  onSavingChange,
  onAudition,
  disabled = false,
  onDraftChange,
}: {
  candidates: Candidate[];
  onChanged: (candidateId: string, accepted: boolean, cueKind: CueKind, position: CuePosition) => void;
  onSavingChange: (delta: number) => void;
  onAudition?: (timeMs: number) => void;
  disabled?: boolean;
  onDraftChange?: (drafting: boolean) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState("all");
  const [type, setType] = useState("all");
  const [editing, setEditing] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, CuePosition>>({});
  const [positionInputs, setPositionInputs] = useState<Record<string, string>>({});
  const [snap, setSnap] = useState<"BEAT" | "BAR">("BEAT");
  const [adjusting, setAdjusting] = useState(false);
  const [positionError, setPositionError] = useState("");
  useEffect(() => { onDraftChange?.(editing !== null || Object.keys(drafts).length > 0); }, [drafts, editing, onDraftChange]);
  const cueMeta = useCueMeta();
  const { kindColor } = useCueColors();
  const kindButtonStyle = (kind: "MEMORY" | "HOT") => ({ background: kindColor(kind), color: colorText(kindColor(kind)) });
  const toast = useToast();

  const decide = async (c: Candidate, accepted: boolean, cueKind: CueKind) => {
    if (disabled || pending[c.id] || adjusting) return;
    setPending((p) => ({ ...p, [c.id]: true }));
    onSavingChange(1);
    try {
      const result = await api.decide(c.id, { accepted, cue_kind: cueKind, ...(drafts[c.id] ? { edited_time_ms: drafts[c.id].time_ms } : {}) });
      onChanged(c.id, accepted, cueKind, { time_ms: result.time_ms ?? drafts[c.id]?.time_ms ?? c.time_ms, beat: result.beat ?? drafts[c.id]?.beat ?? c.beat });
      setDrafts((current) => { const next = { ...current }; delete next[c.id]; return next; });
      if (editing === c.id) setEditing(null);
      const label = accepted ? `採用 (${CUE_KIND_LABEL[cueKind]})` : "却下";
      const meta = cueMeta(c.type);
      toast.push(
        accepted ? "success" : "info",
        `${meta.label} ${fmtTime(c.time_ms)} を${label}しました`,
      );
    } catch (e) {
      toast.push("error", `判定に失敗: ${e}`);
    } finally {
      setPending((p) => ({ ...p, [c.id]: false }));
      onSavingChange(-1);
    }
  };

  const preview = async (candidate: Candidate, step = 0, fromOriginal = false) => {
    if (disabled || adjusting) return;
    setPositionError("");
    const timeMs = fromOriginal ? candidate.original_time_ms ?? candidate.time_ms : step ? drafts[candidate.id]?.time_ms ?? candidate.time_ms : Math.round(Number(positionInputs[candidate.id] ?? candidate.time_ms / 1000) * 1000);
    if (!Number.isFinite(timeMs) || timeMs < 0 || positionInputs[candidate.id] === "") { setPositionError("曲の範囲内の秒数を入力してください。"); return; }
    setAdjusting(true);
    try {
      const position = await api.previewPosition(candidate.id, timeMs, fromOriginal ? "BEAT" : snap, step);
      setDrafts((current) => ({ ...current, [candidate.id]: position }));
      setPositionInputs((current) => ({ ...current, [candidate.id]: (position.time_ms / 1000).toFixed(3) }));
    } catch (error) { setPositionError(error instanceof Error ? error.message : String(error)); }
    finally { setAdjusting(false); }
  };

  if (candidates.length === 0)
    return (
      <div className="empty">
        <span className="emoji">🔍</span>
        候補はまだありません。解析が完了すると表示されます。
      </div>
    );

  const visible = candidates.filter((c) => (type === "all" || c.type === type) && (
    filter === "all" || (filter === "undecided" && c.accepted == null) ||
    (filter === "accepted" && c.accepted === true) || (filter === "high" && c.band === "high") ||
    (filter === "memory" && c.accepted === true && (c.cue_kind === "MEMORY" || c.cue_kind === "BOTH")) ||
    (filter === "hot" && c.accepted === true && (c.cue_kind === "HOT" || c.cue_kind === "BOTH"))
  ));

  return (
    <>
    <div className="cue-kind-guide">
      <p><strong><CueKindSwatch kind="MEMORY" />Memory Cue</strong><span>曲の展開やミックス位置の目印に。</span></p>
      <p><strong><CueKindSwatch kind="HOT" />Hot Cue</strong><span>再生位置をすぐ呼び出したい場所に。</span></p>
      <p><strong><CueKindSwatch kind="BOTH" />両方</strong><span>同じ位置に Memory Cue と Hot Cue を登録。</span></p>
    </div>
    <p className="field-help">候補ごとに採用方法を選べます。選択は保存され、後から変更できます。</p>
    <div className="candidate-filters">
      <label htmlFor="cue-filter">表示<select id="cue-filter" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">すべて</option><option value="undecided">未判定</option><option value="accepted">採用済み</option><option value="memory">Memory Cue を採用</option><option value="hot">Hot Cue を採用</option><option value="high">信頼度が高い</option></select></label>
      <label htmlFor="cue-type">種別<select id="cue-type" value={type} onChange={(e) => setType(e.target.value)}><option value="all">すべての種別</option>{Array.from(new Set(candidates.map((c) => c.type))).map((t) => <option key={t} value={t}>{cueMeta(t).label}</option>)}</select></label>
      <span className="muted" role="status">{visible.length} / {candidates.length} 件</span>
    </div>
    <p className="table-scroll-hint field-help">表を横にスクロールすると、判定と採用ボタンを確認できます。</p>
    <div className="table-scroll" tabIndex={0} role="region" aria-label="キュー候補一覧">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>種別</th>
          <th>時刻</th>
          <th>ビート</th>
          <th style={{ minWidth: 120 }}>信頼度</th>
          <th>判定</th>
          <th style={{ textAlign: "right" }}>操作</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((c) => {
          const meta = cueMeta(c.type);
          const decision = c.accepted == null ? "未判定" : c.accepted ? `採用 (${CUE_KIND_LABEL[c.cue_kind ?? "MEMORY"]})` : "却下";
          return (
            <Fragment key={c.id}>
              <tr>
                <td className="mono muted">{c.rank}</td>
                <td>
                  <span className="chip" style={{ background: meta.color }}>
                    {meta.icon} {meta.label}
                  </span>
                </td>
                <td className="mono">{fmtTime(drafts[c.id]?.time_ms ?? c.time_ms)}{drafts[c.id] && <div className="field-help">調整中・未保存</div>}{!drafts[c.id] && c.original_time_ms != null && c.original_time_ms !== c.time_ms && <div className="field-help">調整済み</div>}</td>
                <td className="mono muted">{c.beat ?? "-"}</td>
                <td>
                  <div className="meter-wrap">
                    <div className={`meter ${c.band}`}>
                      <span style={{ width: `${c.confidence}%` }} />
                    </div>
                    <span className="meter-val">{c.confidence}</span>
                    <span className={`badge ${c.band}`}>{({ high: "高", review: "要確認", reject: "低" })[c.band]}</span>
                  </div>
                </td>
                <td>
                  <span className={c.accepted ? "decision-accepted" : "muted"} style={{ fontSize: 12 }}>{c.accepted && <CueKindSwatch kind={c.cue_kind ?? "MEMORY"} />}{pending[c.id] ? "保存中…" : decision}</span>
                </td>
                <td>
                  <div className="cue-decision-actions">
                    <button className="tiny" style={kindButtonStyle("MEMORY")} disabled={disabled || pending[c.id] || adjusting} aria-pressed={c.accepted === true && c.cue_kind === "MEMORY"} onClick={() => decide(c, true, "MEMORY")}>
                      Memory Cue
                    </button>
                    <button className="tiny" style={kindButtonStyle("HOT")} disabled={disabled || pending[c.id] || adjusting} aria-pressed={c.accepted === true && c.cue_kind === "HOT"} onClick={() => decide(c, true, "HOT")}>
                      Hot Cue
                    </button>
                    <button className="secondary tiny" disabled={disabled || pending[c.id] || adjusting} aria-pressed={c.accepted === true && c.cue_kind === "BOTH"} onClick={() => decide(c, true, "BOTH")}><CueKindSwatch kind="BOTH" />両方</button>
                    <button type="button" className="secondary tiny" disabled={!onAudition} onClick={() => onAudition?.(drafts[c.id]?.time_ms ?? c.time_ms)}>試聴</button>
                    <button type="button" className="secondary tiny" disabled={disabled || pending[c.id] || adjusting} aria-expanded={editing === c.id} onClick={() => { setEditing(editing === c.id ? null : c.id); setPositionError(""); }}>位置を調整</button>
                    <button className="secondary tiny" disabled={disabled || pending[c.id] || adjusting} onClick={() => decide(c, false, c.cue_kind ?? "MEMORY")}>
                      却下
                    </button>
                    <button
                      className="secondary tiny"
                      aria-expanded={open === c.id}
                      onClick={() => setOpen(open === c.id ? null : c.id)}
                    >
                      {open === c.id ? "▲" : "根拠"}
                    </button>
                  </div>
                </td>
              </tr>
              {editing === c.id && <tr><td colSpan={7} className="candidate-position-editor">
                <p className="field-help">試聴して位置を合わせ、Hot Cue／Memory Cue／両方の採用ボタンで保存します。調整だけでは判定・XMLは変更しません。</p>
                <div className="row">
                  <label>時刻（秒）<input type="number" min="0" step="0.001" aria-label="Cueを置く時刻（秒）" value={positionInputs[c.id] ?? ((drafts[c.id]?.time_ms ?? c.time_ms) / 1000).toFixed(3)} disabled={adjusting} onChange={(e) => setPositionInputs((current) => ({ ...current, [c.id]: e.target.value }))} /></label>
                  <label>位置を合わせる単位<select value={snap} aria-label="Cue位置の調整単位" disabled={adjusting} onChange={(e) => setSnap(e.target.value as "BEAT" | "BAR")}><option value="BEAT">拍</option><option value="BAR">小節頭</option></select></label>
                  <button type="button" className="secondary tiny" disabled={adjusting} onClick={() => preview(c)}>時刻を合わせる</button>
                  <button type="button" className="secondary tiny" disabled={adjusting} onClick={() => preview(c, -1)}>← 1{snap === "BEAT" ? "拍" : "小節"}</button>
                  <button type="button" className="secondary tiny" disabled={adjusting} onClick={() => preview(c, 1)}>1{snap === "BEAT" ? "拍" : "小節"} →</button>
                  <button type="button" className="secondary tiny" disabled={!onAudition || adjusting} onClick={() => onAudition?.(drafts[c.id]?.time_ms ?? c.time_ms)}>調整位置を試聴</button>
                  <button type="button" className="secondary tiny" disabled={adjusting} onClick={() => preview(c, 0, true)}>元の解析位置へ</button>
                  <button type="button" className="secondary tiny" disabled={adjusting} onClick={() => { setDrafts((current) => { const next = { ...current }; delete next[c.id]; return next; }); setPositionInputs((current) => { const next = { ...current }; delete next[c.id]; return next; }); setEditing(null); }}>調整を破棄</button>
                </div>
                {positionError && <p className="error" role="alert">{positionError}</p>}
              </td></tr>}
              {open === c.id && (
                <tr>
                  <td colSpan={7} style={{ background: "rgba(0,0,0,0.18)" }}>
                    <Evidence c={c} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
    </div>
    {visible.length === 0 && <p className="field-help">この条件に一致する候補はありません。</p>}
    </>
  );
}
