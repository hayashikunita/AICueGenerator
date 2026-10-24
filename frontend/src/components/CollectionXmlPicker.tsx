import { useState } from "react";
import { api } from "../api";
import type { CollectionXml } from "../types";

const KEY = "aicue.collectionXml";
export function savedCollectionXml(): CollectionXml | null {
  try {
    const info = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return info && /^[0-9a-f]{32}$/.test(info.source_id) && typeof info.filename === "string" ? info : null;
  } catch { return null; }
}
export function storeCollectionXml(value: CollectionXml | null) {
  try { if (value) localStorage.setItem(KEY, JSON.stringify(value)); else localStorage.removeItem(KEY); } catch { /* Reading/uploading still works without browser storage. */ }
}

export function CollectionXmlPicker({ value, onChange, disabled, onBusy }: { value: CollectionXml | null; onChange: (value: CollectionXml | null) => void; disabled: boolean; onBusy: (busy: boolean) => void }) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  return <section className="collection-xml-picker" aria-label="既存Cueを保持するためのコレクションXML">
    <strong>最新のコレクションXMLを選ぶ</strong>
    <p className="field-help">rekordboxで変更を保存し、「ファイル → コレクションをxml形式でエクスポート」でXMLを保存してから選んでください。アプリが作ったXMLは使いません。</p>
    <label>rekordboxから書き出したXML<input type="file" accept=".xml,application/xml,text/xml" aria-label="元のコレクションXMLを選択" disabled={disabled || loading} onChange={async (event) => {
      const file = event.currentTarget.files?.[0];
      event.currentTarget.value = "";
      if (!file) return;
      setError(""); onChange(null);
      if (file.size > 20 * 1024 * 1024) { setError("20MB以下のXMLを選んでください。"); return; }
      setLoading(true); onBusy(true);
      try { onChange(await api.uploadCollectionXml(file.name, await file.text())); }
      catch (problem) { setError(problem instanceof Error ? problem.message : String(problem)); }
      finally { setLoading(false); onBusy(false); }
    }} /></label>
    {loading && <p className="field-help" role="status">コレクションXMLを読み込んでいます…</p>}
    {value && <p className="field-help collection-xml-name">選択中：{value.filename}（{value.tracks}曲）</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <p className="field-help">元曲のパスと既存Cue・ループ・グリッドを照合します。rekordbox側で編集した後は、XMLをもう一度書き出して選び直してください。</p>
  </section>;
}
