import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Diagnostics as Diag } from "../types";

function Item({ ok, warn, label }: { ok: boolean; warn?: boolean; label: string }) {
  const cls = ok ? "ok" : warn ? "warn" : "bad";
  return (
    <span className="pill">
      <span className={`dot ${cls}`} />
      {label}
    </span>
  );
}

export function Diagnostics() {
  const [d, setD] = useState<Diag | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    setErr(null);
    api
      .diagnostics()
      .then(setD)
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  }, []);

  useEffect(load, [load]);

  if (err) return <div className="panel error" role="alert">接続状態を確認できませんでした: {err}<button className="secondary tiny" onClick={load} disabled={busy}>再試行</button></div>;
  if (!d)
    return (
      <div className="panel">
        <div className="row" style={{ gap: 12 }}>
          <div className="skeleton" style={{ width: 120 }} />
          <div className="skeleton" style={{ width: 90 }} />
          <div className="skeleton" style={{ width: 110 }} />
        </div>
      </div>
    );

  return (
    <div className="panel">
      <div className="banner">
        <Item ok={!d.process_running} warn={d.process_running} label={d.process_running ? "rekordbox 起動中" : "rekordbox 停止"} />
        <span className="pill">ライブラリDBは読み取り専用</span>
        <span className="spacer" />
        <button className="secondary tiny" disabled={busy} onClick={load}>
          {busy ? "確認中…" : "再診断"}
        </button>
      </div>
      <p className="field-help">解析済みデータを参照します。小節頭は対象曲を確認して保存した場合のみ変更します。新しい Cue は XML へ書き出せます。</p>
      <details className="diagnostic-details"><summary>連携の詳細</summary><div className="row" style={{ marginTop: 10 }}><Item ok={d.db_key_available} label={d.db_key_available ? "復号モジュールあり" : "復号モジュールを確認してください"} /></div></details>
    </div>
  );
}
