import { useEffect, useState } from "react";
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

  const load = () => {
    setBusy(true);
    api
      .diagnostics()
      .then(setD)
      .catch((e) => setErr(String(e)))
      .finally(() => setBusy(false));
  };

  useEffect(load, []);

  if (err) return <div className="panel error">診断取得エラー: {err}</div>;
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
        <Item ok={d.db_key_available} label="DB鍵" />
        <Item ok={d.schema_supported} warn={!d.schema_supported} label="スキーマ対応" />
        <Item ok={d.writable} warn={!d.writable} label={d.writable ? "書込可" : "書込ロック(読取専用)"} />
        <span className="spacer" />
        <button className="secondary tiny" disabled={busy} onClick={load}>
          {busy ? "確認中…" : "再診断"}
        </button>
      </div>
    </div>
  );
}
