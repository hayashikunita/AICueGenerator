import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtTime } from "../cues";
import type { Candidate, ExportMode, ExportXmlResult, WritePlan } from "../types";
import { useToast } from "./Toast";
import { useCueColors } from "./CueColors";
import { CueKindSwatch } from "./CueKindSwatch";
import { RekordboxImportGuide } from "./RekordboxImportGuide";
import { CUE_LIMITS } from "../cueKinds";
import { highestConfidenceMemory, MemoryExportPicker } from "./MemoryExportPicker";
import { CollectionXmlPicker, savedCollectionXml, storeCollectionXml } from "./CollectionXmlPicker";

function ActionBadge({ action }: { action: string }) {
  const map: Record<string, string> = {
    ADD: "high",
    KEEP: "review",
    REPLACE: "review",
    CONFLICT: "reject",
    SKIP: "review",
  };
  const labels: Record<string, string> = { ADD: "追加", KEEP: "維持", REPLACE: "置換", CONFLICT: "競合", SKIP: "重複を省略" };
  return <span className={`badge ${map[action] ?? "review"}`}>{labels[action] ?? action}</span>;
}

export function WritePlanPanel({ jobId, acceptedCount, memoryCount, hotCount, cueCounts, trackNames, deciding, candidates, onAudition, trackIds, scopeLabel, onBusyChange }: { jobId: string; acceptedCount: number; memoryCount: number; hotCount: number; cueCounts: { trackId: string; title: string; memory: number; hot: number }[]; trackNames: Record<string, string>; deciding: boolean; candidates: Candidate[]; onAudition?: (timeMs: number, trackId?: string | null) => void; trackIds: string[]; scopeLabel: string; onBusyChange: (busy: boolean) => void }) {
  const [plan, setPlan] = useState<WritePlan | null>(null);
  const [xmlResult, setXmlResult] = useState<ExportXmlResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<ExportMode>(() => { try { return localStorage.getItem("aicue.exportMode") === "COPY" ? "COPY" : "EXISTING"; } catch { return "EXISTING"; } });
  const [source, setSource] = useState(savedCollectionXml);
  const [sourceBusy, setSourceBusy] = useState(false);
  useEffect(() => {
    onBusyChange(busy || sourceBusy);
    return () => onBusyChange(false);
  }, [busy, sourceBusy, onBusyChange]);
  const [existingReviewed, setExistingReviewed] = useState(false);
  const [memoryIds, setMemoryIds] = useState(() => highestConfidenceMemory(candidates));
  const [memoryReviewed, setMemoryReviewed] = useState(false);
  const toast = useToast();
  const { exportColor } = useCueColors();
  const selectedPerTrack = (trackId: string) => candidates.filter((candidate) => memoryIds.includes(candidate.id) && (candidate.track_id ?? (cueCounts.length === 1 ? cueCounts[0].trackId : "single")) === trackId).length;
  const overflow = mode === "COPY" && cueCounts.some((counts) => selectedPerTrack(counts.trackId) > CUE_LIMITS.MEMORY || counts.hot > CUE_LIMITS.HOT);
  const autoLimited = cueCounts.some((counts) => counts.memory > CUE_LIMITS.MEMORY);
  const noOutput = memoryIds.length + hotCount === 0;
  const changeMemorySelection = (ids: string[]) => { setMemoryIds(ids); setMemoryReviewed(false); setExistingReviewed(false); setPlan(null); setXmlResult(null); };
  const colors = { MEMORY: exportColor("MEMORY"), HOT: exportColor("HOT")! };
  const colorKey = JSON.stringify(colors);
  useEffect(() => { setPlan(null); setExistingReviewed(false); setXmlResult(null); }, [colorKey]);
  const existingReady = mode !== "EXISTING" || !!source;
  const confirmedExisting = mode !== "EXISTING" || (plan?.mode === "EXISTING" && plan.conflict === 0 && plan.add > 0 && existingReviewed);

  const build = async () => {
    setPlan(null);
    setBusy(true);
    try {
      const p = await api.buildPlan(jobId, memoryIds, { mode, source_id: mode === "EXISTING" ? source?.source_id : undefined, cue_colors: colors, track_ids: trackIds });
      setPlan(p);
      setExistingReviewed(false);
      toast.push("info", `プランを作成: 追加 ${p.add} · 置換 ${p.replace} · 競合 ${p.conflict}`);
    } catch (e) {
      toast.push("error", `プラン作成失敗: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const exportXml = async () => {
    setBusy(true);
    try {
      const r = await api.exportXml(jobId, colors, memoryIds, { mode, source_id: mode === "EXISTING" ? source?.source_id : undefined, confirmation_hash: mode === "EXISTING" ? plan?.confirmation_hash : undefined, track_ids: trackIds });
      setXmlResult(r);
      toast.push(
        "success",
        `rekordbox XML を書き出し: 楽曲 ${r.tracks} ・キュー ${r.cues}`
      );
    } catch (e) {
      if (mode === "EXISTING") { setPlan(null); setExistingReviewed(false); }
      toast.push("error", `XML 書き出し失敗: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>3. 採用したキューを書き出す</h2>
      <p className="export-scope"><strong>書き出し対象：{scopeLabel}</strong></p>
      <label htmlFor="xml-export-mode">Cueの反映先<select id="xml-export-mode" value={mode} disabled={busy || deciding || sourceBusy} onChange={(event) => {
        const next = event.target.value as ExportMode; setMode(next); setPlan(null); setXmlResult(null); setExistingReviewed(false);
        try { localStorage.setItem("aicue.exportMode", next); } catch { /* The current choice remains usable. */ }
      }}><option value="EXISTING">既存の曲へCueを追加（元の音源を使う）</option><option value="COPY">複製した曲へCueを付ける</option></select></label>
      {mode === "EXISTING" && <><p className="field-help">元曲のCueを更新するためのXMLを作ります。既存Cue・ループ・曲情報・グリッドを保持し、新しいCueだけを追加します。書き出しただけではrekordboxは更新されません。</p><CollectionXmlPicker value={source} onChange={(value) => { setSource(value); storeCollectionXml(value); setPlan(null); setXmlResult(null); setExistingReviewed(false); }} disabled={busy || deciding} onBusy={setSourceBusy} /></>}
      <p className="field-help">{acceptedCount === 0 ? "上の候補を「Memory Cue」「Hot Cue」「両方」で採用すると、書き出せます。" : `採用済みMemory Cue ${memoryCount} 件のうち ${memoryIds.length} 件・Hot Cue ${hotCount} 件、合計 ${memoryIds.length + hotCount} キューを書き出します。`}</p>
      <p className="field-help">{mode === "EXISTING" ? "既存Cue・ループを含めて" : "XML出力だけを"}1曲につき Memory Cue {CUE_LIMITS.MEMORY}件・Hot Cue {CUE_LIMITS.HOT}件までにします。候補の表示・Memory Cueの採用数は10件に制限しません。</p>
      {cueCounts.length > 0 && <div className="cue-capacity-list" aria-label="曲ごとのCue使用数">{cueCounts.map((counts) => {
        const count = selectedPerTrack(counts.trackId);
        const over = count > CUE_LIMITS.MEMORY || counts.hot > CUE_LIMITS.HOT;
        return <div key={counts.trackId} className={`cue-capacity${over ? " error" : ""}`} role={over ? "alert" : undefined}><strong>{counts.title}</strong><span>Memory Cue：採用 {counts.memory}件 → XML {count}/{CUE_LIMITS.MEMORY} · Hot Cue：XML {counts.hot}/{CUE_LIMITS.HOT}</span>{over && <span>XML出力の上限を超えています。出力するCueを選び直してください。採用した候補はそのまま残せます。</span>}</div>;
      })}</div>}
      <MemoryExportPicker candidates={candidates} selectedIds={memoryIds} trackNames={trackNames} onChange={changeMemorySelection} disabled={busy || deciding} onAudition={onAudition} />
      {autoLimited && <label className="inline-check memory-export-confirm"><input type="checkbox" checked={memoryReviewed} disabled={busy || deciding} onChange={(event) => setMemoryReviewed(event.target.checked)} />自動選択されたXML出力対象を確認しました（候補・採用状態はすべて保持）</label>}
      {trackIds.length > 1 && <p className="field-help">「{scopeLabel}」から選んだCueを1つのXMLにまとめます。上の曲ごとの絞り込みは候補の表示だけを変更します。</p>}
      {candidates.some((candidate) => candidate.preset) ? <p className="field-help">解析前の共通設定・目的別設定の色を使います。候補一覧と書き出し確認の色見本で確認できます。</p> : <><div className="cue-kind-legend" aria-label="XMLに書き出すCueの色"><span><CueKindSwatch kind="MEMORY" />Memory Cue</span><span><CueKindSwatch kind="HOT" />Hot Cue</span></div><p className="field-help">「キュー色設定」の色を、次に書き出す採用Cueへ適用します。Memory Cueの色がrekordboxで反映されるかは未確認です。</p></>}
      <div className="row">
        <button className="secondary" disabled={busy || deciding || sourceBusy || !existingReady || acceptedCount === 0 || noOutput || overflow} onClick={build}>
          書き出すキューを確認
        </button>
        <button disabled={busy || deciding || sourceBusy || !existingReady || !confirmedExisting || acceptedCount === 0 || noOutput || overflow || (autoLimited && !memoryReviewed)} onClick={exportXml}>
          📁 rekordbox XML を書き出し
        </button>
      </div>

      {plan && (
        <>
          <div className="stats" style={{ marginTop: 14 }}>
            <div className="stat">
              <div className="stat-val" style={{ color: "var(--high)" }}>{plan.add}</div>
              <div className="stat-label">追加</div>
            </div>
            <div className="stat">
              <div className="stat-val" style={{ color: "var(--review)" }}>{plan.replace}</div>
              <div className="stat-label">置換</div>
            </div>
            <div className="stat">
              <div className="stat-val" style={{ color: plan.conflict > 0 ? "var(--reject)" : "inherit" }}>
                {plan.conflict}
              </div>
              <div className="stat-label">競合</div>
            </div>
          </div>
          {plan.mode === "EXISTING" && <div className="existing-update-review" aria-label="既存曲への追加内容">
            <p>既存を維持：{plan.preserved ?? 0}件 ／ 新しく追加：{plan.add}件 ／ 重複を省略：{plan.duplicates_skipped ?? 0}件</p>
            {plan.track_updates?.map((track) => <div key={track.track_id} className="cue-capacity"><strong>{track.title}</strong><span>Memory：既存 {track.existing_memory} ＋ 追加 {track.add_memory} / 10 · Hot：既存 {track.existing_hot} ＋ 追加 {track.add_hot} / 8</span><span className="mono">元曲：{track.path}</span></div>)}
            {plan.issues?.map((issue, index) => <p className="error" role="alert" key={index}>{issue}</p>)}
            {plan.conflict === 0 && plan.add > 0 && <label className="inline-check"><input type="checkbox" className="existing-update-confirm" checked={existingReviewed} disabled={busy || deciding} onChange={(event) => setExistingReviewed(event.target.checked)} />既存Cueの維持と、元曲へ追加する内容を確認しました</label>}
            {plan.conflict === 0 && plan.add === 0 && <p className="field-help">追加する新しいCueはありません。同じ位置のCueは既存のまま保持します。</p>}
          </div>}

          {plan.conflict > 0 && plan.mode !== "EXISTING" && <p className="error">出力対象に同じ種別・位置の重複があります。書き出す候補を選び直して内容を再確認してください。</p>}
          <div className="table-scroll" tabIndex={0} role="region" aria-label="書き込み内容"><table style={{ marginTop: 6 }}>
            <thead>
              <tr>
                <th>トラック</th>
                <th>種別</th>
                <th>操作</th>
                <th>時刻</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody>
              {plan.items.map((i, idx) => {
                return (
                  <tr key={idx}>
                    <td className="candidate-track-name">{trackNames[i.track_id] ?? i.track_id}</td>
                    <td>{i.action === "KEEP" ? <span className={`cue-kind-swatch${i.cue_kind === "MEMORY" ? " memory" : ""}`} style={{ background: i.color ?? "transparent" }} aria-hidden="true" /> : <CueKindSwatch kind={i.cue_kind === "HOT" ? "HOT" : "MEMORY"} preset={i.preset} />}{i.cue_kind === "HOT" ? `Hot Cue${i.slot ? ` ${i.slot}` : ""}` : "Memory Cue"}</td>
                    <td><ActionBadge action={i.action} /></td>
                    <td className="mono">{fmtTime(i.time_ms)}{i.end_time_ms != null ? `〜${fmtTime(i.end_time_ms)}` : ""}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{i.reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        </>
      )}

      {busy && <p className="field-help" role="status">処理しています…</p>}

      {xmlResult && (
        <>
        <div className="log" style={{ marginTop: 12 }}>
          <div>✓ rekordbox XML を書き出しました（楽曲 {xmlResult.tracks} ・キュー {xmlResult.cues} ・複製 {xmlResult.copied}）</div>
          {xmlResult.mode === "EXISTING" && <><p className="field-help">既存Cue {xmlResult.preserved_cues}件を維持し、新しいCue {xmlResult.added_cues}件を追加するXMLです。音源は複製していません。rekordboxで取り込むと元曲が更新対象になります。</p><p className="field-help">元コレクションXMLの控え：<span className="mono">{xmlResult.backup_xml_path}</span></p></>}
          {xmlResult.cue_settings_used ? <p className="field-help">書き出した色：解析前の共通設定・目的ごとの色を各Cueに反映しました。</p> : xmlResult.cue_colors && <p className="field-help">書き出した色：Memory Cue {xmlResult.cue_colors.MEMORY ?? "未設定"} ／ Hot Cue {xmlResult.cue_colors.HOT ?? "未指定"}</p>}
          {xmlResult.warnings?.map((warning) => <p key={warning} className="field-help">{warning}</p>)}
          <div className="mono muted" style={{ fontSize: 12, marginTop: 6, wordBreak: "break-all" }}>
            {xmlResult.folder}
          </div>
          {xmlResult.skipped.length > 0 && (
            <ul className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              {xmlResult.skipped.map((s, i) => (
                <li key={i}>⚠ {s}</li>
              ))}
            </ul>
          )}
        </div>
        <RekordboxImportGuide xmlPath={xmlResult.xml_path} existing={xmlResult.mode === "EXISTING"} />
        </>
      )}

    </div>
  );
}
