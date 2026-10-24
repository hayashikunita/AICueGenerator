import { useState } from "react";
import { api } from "../api";
import { ALL_CUE_TARGETS as CUE_TARGETS } from "../cueTargets";
import type { CueTarget } from "../types";

export function ManualCueForm({ jobId, trackId, currentTimeMs, onAdded, disabled, onBusy }: {
  jobId: string; trackId: string; currentTimeMs: number; onAdded: () => void | Promise<void>;
  disabled: boolean; onBusy: (busy: boolean) => void;
}) {
  const [target, setTarget] = useState<CueTarget>("VOCAL_START");
  const [seconds, setSeconds] = useState("0");
  const [snap, setSnap] = useState<"BEAT" | "BAR">("BEAT");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  return <details className="manual-cue-form">
    <summary>見つからなかった位置を、試聴して候補に追加</summary>
    <p className="field-help">自動で特定できない歌い始めなどを補えます。追加後にHot Cue／Memory Cueを選んで採用してください。</p>
    <form onSubmit={async (event) => {
      event.preventDefault();
      if (busy || disabled) return;
      setError(""); setMessage("");
      if (!seconds.trim() || !Number.isFinite(Number(seconds)) || Number(seconds) < 0) { setError("曲の範囲内の秒数を入力してください。"); return; }
      setBusy(true); onBusy(true);
      try {
        await api.addManualCandidate(jobId, trackId, target, Math.round(Number(seconds) * 1000), snap);
        await onAdded();
        setMessage("確認用の候補を追加しました。試聴して採用方法を選んでください。");
      } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
      finally { setBusy(false); onBusy(false); }
    }}>
      <fieldset disabled={busy || disabled}>
        <label htmlFor="manual-cue-target">Cueの位置</label><select id="manual-cue-target" value={target} onChange={(e) => setTarget(e.target.value as CueTarget)}>{CUE_TARGETS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
        <label htmlFor="manual-cue-seconds">ここに置きたい時刻（秒）</label>
        <div className="search-row"><input id="manual-cue-seconds" type="number" min="0" step="0.001" required value={seconds} onChange={(e) => setSeconds(e.target.value)} /><button type="button" className="secondary tiny" onClick={() => setSeconds((currentTimeMs / 1000).toFixed(3))}>再生位置を使う</button></div>
        <label htmlFor="manual-cue-snap">位置を合わせる単位</label><select id="manual-cue-snap" value={snap} onChange={(e) => setSnap(e.target.value as "BEAT" | "BAR")}><option value="BEAT">最寄りの拍</option><option value="BAR">最寄りの小節頭</option></select>
        <button type="submit" className="secondary manual-cue-add">{busy ? "追加中…" : "確認用の候補を追加"}</button>
      </fieldset>
    </form>
    {disabled && <p className="field-help">候補の保存・位置調整を終えてから追加してください。</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p className="field-help" role="status">{message}</p>}
  </details>;
}
