import { useState } from "react";
import { api } from "../api";
import type { ExecuteResult, WritePlan } from "../types";

function fmt(ms: number): string {
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export function WritePlanPanel({ jobId, writable }: { jobId: string; writable: boolean }) {
  const [plan, setPlan] = useState<WritePlan | null>(null);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const build = async () => {
    setErr(null);
    setResult(null);
    setBusy(true);
    try {
      setPlan(await api.buildPlan(jobId));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const execute = async () => {
    if (!plan) return;
    setErr(null);
    setBusy(true);
    try {
      setResult(await api.executePlan(plan.plan_id, plan.confirmation_hash));
    } catch (e) {
      setErr(String(e));
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
        {plan && (
          <button className="danger" disabled={busy || !writable || plan.conflict > 0} onClick={execute}>
            rekordbox へ書き込み
          </button>
        )}
      </div>
      {err && <p className="error">{err}</p>}

      {plan && (
        <>
          <p className="muted" style={{ marginTop: 12 }}>
            追加 {plan.add} · 置換 {plan.replace} · 競合 {plan.conflict} ·{" "}
            <span className="mono">hash {plan.confirmation_hash.slice(0, 18)}…</span>
          </p>
          {!writable && (
            <p className="error">
              書込ロック中（rekordbox 起動中・スキーマ未対応・容量不足のいずれか）。実行はフェイルクローズで拒否されます。
            </p>
          )}
          <table>
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
              {plan.items.map((i, idx) => (
                <tr key={idx}>
                  <td className="mono">{i.track_id.slice(0, 10)}…</td>
                  <td>{i.cue_kind}</td>
                  <td>{i.action}</td>
                  <td className="mono">{fmt(i.time_ms)}</td>
                  <td className="muted">{i.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {result && (
        <div className="log" style={{ marginTop: 12 }}>
          {result.ok
            ? `書き込み成功: ${result.written} 件`
            : `拒否 (${result.error_code}): ${result.message}`}
        </div>
      )}
    </div>
  );
}
