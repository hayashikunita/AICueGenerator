import { useState } from "react";
import { api } from "../api";
import { fmtTime } from "../cues";
import type { ExportXmlResult, WritePlan } from "../types";
import { useToast } from "./Toast";
import { useCueColors } from "./CueColors";
import { CueKindSwatch } from "./CueKindSwatch";

function ActionBadge({ action }: { action: string }) {
  const map: Record<string, string> = {
    ADD: "high",
    KEEP: "review",
    REPLACE: "review",
    CONFLICT: "reject",
  };
  const labels: Record<string, string> = { ADD: "追加", KEEP: "維持", REPLACE: "置換", CONFLICT: "競合" };
  return <span className={`badge ${map[action] ?? "review"}`}>{labels[action] ?? action}</span>;
}

export function WritePlanPanel({ jobId, acceptedCount, memoryCount, hotCount, deciding }: { jobId: string; acceptedCount: number; memoryCount: number; hotCount: number; deciding: boolean }) {
  const [plan, setPlan] = useState<WritePlan | null>(null);
  const [xmlResult, setXmlResult] = useState<ExportXmlResult | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const { kindColor } = useCueColors();

  const build = async () => {
    setPlan(null);
    setBusy(true);
    try {
      const p = await api.buildPlan(jobId);
      setPlan(p);
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
      const r = await api.exportXml(jobId, { MEMORY: kindColor("MEMORY"), HOT: kindColor("HOT") });
      setXmlResult(r);
      toast.push(
        "success",
        `rekordbox XML を書き出し: 楽曲 ${r.tracks} ・キュー ${r.cues}`
      );
    } catch (e) {
      toast.push("error", `XML 書き出し失敗: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>3. 採用したキューを書き出す</h2>
      <p className="field-help">{acceptedCount === 0 ? "上の候補を「Memory Cue」「Hot Cue」「両方」で採用すると、書き出せます。" : `Memory Cue ${memoryCount} 件・Hot Cue ${hotCount} 件、合計 ${memoryCount + hotCount} キューを書き出します。「両方」の候補は各 1 件ずつ含まれます。`}</p>
      {hotCount > 8 && <p className="field-help">Hot Cue の XML 出力は 1 曲につき A〜H の 8 件までです。超える場合は、使い分けて Memory Cue に変更してください。</p>}
      <div className="cue-kind-legend" aria-label="XMLに書き出すCueの色"><span><CueKindSwatch kind="MEMORY" />Memory Cue</span><span><CueKindSwatch kind="HOT" />Hot Cue</span></div>
      <p className="field-help">「キュー色設定」の色を、次に書き出す採用Cueへ適用します。Memory Cueの色がrekordboxで反映されるかは未確認です。</p>
      <div className="row">
        <button className="secondary" disabled={busy || deciding || acceptedCount === 0} onClick={build}>
          書き出すキューを確認
        </button>
        <button disabled={busy || deciding || acceptedCount === 0} onClick={exportXml}>
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

          {plan.conflict > 0 && <p className="error">採用候補に同じ種別・位置の重複があります。採用する候補を変更して内容を再確認してください。</p>}
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
                    <td className="mono muted">{i.track_id.slice(0, 10)}…</td>
                    <td><CueKindSwatch kind={i.cue_kind === "HOT" ? "HOT" : "MEMORY"} />{i.cue_kind === "HOT" ? "Hot Cue" : "Memory Cue"}</td>
                    <td><ActionBadge action={i.action} /></td>
                    <td className="mono">{fmtTime(i.time_ms)}</td>
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
        <div className="log" style={{ marginTop: 12 }}>
          <div>✓ rekordbox XML を書き出しました（楽曲 {xmlResult.tracks} ・キュー {xmlResult.cues} ・複製 {xmlResult.copied}）</div>
          {xmlResult.cue_colors && <p className="field-help">書き出した色：Memory Cue {xmlResult.cue_colors.MEMORY ?? "未指定"} ／ Hot Cue {xmlResult.cue_colors.HOT ?? "未指定"}</p>}
          {xmlResult.warnings?.map((warning) => <p key={warning} className="field-help">{warning}</p>)}
          <div className="mono muted" style={{ fontSize: 12, marginTop: 6, wordBreak: "break-all" }}>
            {xmlResult.folder}
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            rekordbox の「ファイル › ライブラリ › rekordbox xml を読み込む」から rekordbox.xml を取り込めます。
          </div>
          {xmlResult.skipped.length > 0 && (
            <ul className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              {xmlResult.skipped.map((s, i) => (
                <li key={i}>⚠ {s}</li>
              ))}
            </ul>
          )}
        </div>
      )}

    </div>
  );
}
