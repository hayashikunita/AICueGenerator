import { useState } from "react";
import { api } from "../api";
import { fmtTime } from "../cues";
import type { ExecuteResult, ExportXmlResult, WritePlan } from "../types";
import { useToast } from "./Toast";

function ActionBadge({ action }: { action: string }) {
  const map: Record<string, string> = {
    ADD: "high",
    KEEP: "review",
    REPLACE: "review",
    CONFLICT: "reject",
  };
  return <span className={`badge ${map[action] ?? "review"}`}>{action}</span>;
}

export function WritePlanPanel({ jobId, writable }: { jobId: string; writable: boolean }) {
  const [plan, setPlan] = useState<WritePlan | null>(null);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [xmlResult, setXmlResult] = useState<ExportXmlResult | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const build = async () => {
    setResult(null);
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

  const execute = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      const r = await api.executePlan(plan.plan_id, plan.confirmation_hash);
      setResult(r);
      if (r.ok) toast.push("success", `rekordbox へ書き込み成功: ${r.written} 件`);
      else toast.push("error", `書き込み拒否 (${r.error_code})`);
    } catch (e) {
      toast.push("error", `実行失敗: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const exportXml = async () => {
    setBusy(true);
    try {
      const r = await api.exportXml(jobId);
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
      <h2>書き込みプラン</h2>
      <div className="row">
        <button className="secondary" disabled={busy} onClick={build}>
          採用キューからプラン作成
        </button>
        <button className="secondary" disabled={busy} onClick={exportXml}>
          📁 rekordbox XML を書き出し
        </button>
        {plan && (
          <button
            className="danger"
            disabled={busy || !writable || plan.conflict > 0}
            onClick={execute}
          >
            🎧 rekordbox へ書き込み
          </button>
        )}
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
            <div className="stat">
              <div className="stat-val mono" style={{ fontSize: 13 }}>
                {plan.confirmation_hash.slice(0, 10)}…
              </div>
              <div className="stat-label">確認ハッシュ</div>
            </div>
          </div>

          {!writable && (
            <p className="error">
              書込ロック中（rekordbox 起動中・スキーマ未対応・容量不足のいずれか）。実行はフェイルクローズで拒否されます。
            </p>
          )}

          <table style={{ marginTop: 6 }}>
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
                    <td>{i.cue_kind}</td>
                    <td><ActionBadge action={i.action} /></td>
                    <td className="mono">{fmtTime(i.time_ms)}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{i.reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}

      {xmlResult && (
        <div className="log" style={{ marginTop: 12 }}>
          <div>✓ rekordbox XML を書き出しました（楽曲 {xmlResult.tracks} ・キュー {xmlResult.cues} ・複製 {xmlResult.copied}）</div>
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

      {result && (
        <div className={result.ok ? "log" : "error"} style={{ marginTop: 12 }}>
          {result.ok
            ? `✓ 書き込み成功: ${result.written} 件`
            : `✕ 拒否 (${result.error_code}): ${result.message}`}
        </div>
      )}
    </div>
  );
}
