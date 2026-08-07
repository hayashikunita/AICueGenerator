import { useState } from "react";
import { api } from "../api";
import { CUE_ORDER } from "../cues";
import type { RekordboxTrack, TrackInput } from "../types";
import { useCueMeta } from "./CueColors";
import { useToast } from "./Toast";

const LEGEND = CUE_ORDER;

function formatFromPath(path: string): string {
  const ext = path.split(".").pop()?.toUpperCase();
  return ext && ext.length <= 4 ? ext : "WAV";
}

export function NewJobForm({ onCreated }: { onCreated: (jobId: string) => void }) {
  const cueMeta = useCueMeta();
  const [path, setPath] = useState("");
  const [contentId, setContentId] = useState("");
  const [bpm, setBpm] = useState("");
  const [barsPerPhrase, setBarsPerPhrase] = useState("16");
  const [topK, setTopK] = useState("3");
  const [busy, setBusy] = useState(false);
  const [rbQuery, setRbQuery] = useState("");
  const [rbResults, setRbResults] = useState<RekordboxTrack[]>([]);
  const [rbSearching, setRbSearching] = useState(false);
  const [rbSearched, setRbSearched] = useState(false);
  const toast = useToast();

  const searchRekordbox = async () => {
    setRbSearching(true);
    setRbSearched(false);
    try {
      const res = await api.searchRekordbox(rbQuery.trim(), 20);
      if (!res.available) {
        toast.push("error", `rekordbox に接続できません: ${res.reason ?? "不明"}`);
        setRbResults([]);
      } else {
        setRbResults(res.tracks);
        if (res.tracks.length === 0) toast.push("info", "該当する曲がありません。");
      }
      setRbSearched(true);
    } catch (e) {
      toast.push("error", `検索に失敗: ${e}`);
    } finally {
      setRbSearching(false);
    }
  };

  const pickTrack = (t: RekordboxTrack) => {
    if (t.path) setPath(t.path);
    setContentId(t.content_id);
    if (t.bpm) setBpm(String(t.bpm));
    setRbResults([]);
    setRbSearched(false);
    toast.push("success", `${t.title ?? t.content_id} を読み込みました`);
  };

  const submit = async () => {
    if (!path.trim()) {
      toast.push("error", "音源ファイルのパスを入力してください。");
      return;
    }
    const track: TrackInput = {
      content_id: contentId.trim() || path.trim(),
      path: path.trim(),
      format: formatFromPath(path.trim()),
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
      toast.push("success", "解析ジョブを開始しました");
      onCreated(job_id);
      setPath("");
      setContentId("");
    } catch (e) {
      toast.push("error", `ジョブ作成失敗: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>新規解析ジョブ</h2>

      <label>rekordbox から選択</label>
      <div className="row" style={{ gap: 6 }}>
        <input
          style={{ flex: 1 }}
          value={rbQuery}
          placeholder="曲名 / アーティストで検索"
          onChange={(e) => setRbQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && searchRekordbox()}
        />
        <button className="tiny" disabled={rbSearching} onClick={searchRekordbox}>
          {rbSearching ? "検索中…" : "🔎 検索"}
        </button>
      </div>
      {rbResults.length > 0 && (
        <div className="rb-results">
          {rbResults.map((t) => (
            <button key={t.content_id} className="rb-item" onClick={() => pickTrack(t)}>
              <span className="rb-title">{t.title ?? "(無題)"}</span>
              <span className="rb-meta">
                {t.artist ?? "-"}
                {t.bpm ? ` · ${t.bpm} BPM` : ""}
              </span>
            </button>
          ))}
        </div>
      )}
      {rbSearched && rbResults.length === 0 && (
        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          該当なし。曲名やアーティスト名を変えて再検索してください。
        </div>
      )}

      <label style={{ marginTop: 14 }}>音源ファイルパス (WAV)</label>
      <input
        value={path}
        placeholder="C:\\music\\track.wav"
        onChange={(e) => setPath(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
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
      <div className="row" style={{ marginTop: 16 }}>
        <button disabled={busy} onClick={submit} style={{ width: "100%" }}>
          {busy ? "送信中…" : "⚡ 解析を開始"}
        </button>
      </div>

      <div className="row" style={{ marginTop: 16, gap: 6 }}>
        {LEGEND.map((t) => {
          const m = cueMeta(t);
          return (
            <span key={t} className="chip" style={{ background: m.color, fontSize: 11 }}>
              {m.icon} {m.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}
