import { useState } from "react";
import { api } from "../api";
import type { TrackInput } from "../types";

export function NewJobForm({ onCreated }: { onCreated: (jobId: string) => void }) {
  const [path, setPath] = useState("");
  const [contentId, setContentId] = useState("");
  const [bpm, setBpm] = useState("");
  const [barsPerPhrase, setBarsPerPhrase] = useState("16");
  const [topK, setTopK] = useState("3");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    if (!path.trim()) {
      setErr("音源ファイルのパスを入力してください。");
      return;
    }
    const track: TrackInput = {
      content_id: contentId.trim() || path.trim(),
      path: path.trim(),
      format: "WAV",
    };
    setBusy(true);
    try {
      const { job_id } = await api.createJob(
        {
          bpm: bpm.trim() ? Number(bpm) : null,
          bars_per_phrase: Number(barsPerPhrase),
          top_k: Number(topK),
        },
        [track],
      );
      onCreated(job_id);
      setPath("");
      setContentId("");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>新規解析ジョブ</h2>
      <label>音源ファイルパス (WAV)</label>
      <input
        value={path}
        placeholder="C:\\music\\track.wav"
        onChange={(e) => setPath(e.target.value)}
      />
      <label>コンテンツID (任意)</label>
      <input value={contentId} placeholder="未指定ならパスを使用" onChange={(e) => setContentId(e.target.value)} />
      <div className="row">
        <div style={{ flex: 1 }}>
          <label>BPM (任意)</label>
          <input value={bpm} placeholder="推定" onChange={(e) => setBpm(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <label>小節/フレーズ</label>
          <input value={barsPerPhrase} onChange={(e) => setBarsPerPhrase(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <label>候補数</label>
          <input value={topK} onChange={(e) => setTopK(e.target.value)} />
        </div>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button disabled={busy} onClick={submit}>
          {busy ? "送信中…" : "解析を開始"}
        </button>
      </div>
      {err && <p className="error">{err}</p>}
    </div>
  );
}
