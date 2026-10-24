import { useEffect, useState } from "react";
import type { JobSummary, JobTrack } from "../types";
import { trackName } from "../jobs";

function duration(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

export function AnalysisProgress({ job, tracks }: { job: JobSummary; tracks: JobTrack[] }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const track = tracks.find((item) => item.status === "RUNNING");
  if (!track) return <p className="field-help" role="status">解析の開始を待っています。完了した曲：{job.completed}/{job.total}</p>;
  const data = track.analysis;
  const progress = data?.ai_progress;
  const vocalOnly = data?.ai_scope === "VOCAL" || progress?.scope === "VOCAL";
  const ai = job.params?.analysis_quality === "AI" && data?.analysis_quality === "AI";
  const start = data?.ai_started_at ? Date.parse(data.ai_started_at) : NaN;
  const elapsed = Number.isFinite(start) ? Math.max(0, (now - start) / 1000) : progress?.elapsed_sec;
  const index = tracks.findIndex((item) => item.id === track.id) + 1;
  return <div className="analysis-progress-info" aria-label="処理中の曲の進捗">
    <strong>{index}/{job.total}曲目：{trackName(track.path, track.title, track.artist)}</strong>
    <p role="status">{data?.stage || "音源の特徴を解析しています。"}</p>
    {ai && <>
      {progress?.percent != null && <>
        <p>{vocalOnly ? "この区間のボーカル分離" : "この曲の音源分離"}：{progress.percent}%</p>
        <progress aria-label="この曲の音源分離" max="100" value={progress.percent} style={{ width: "100%", accentColor: "#1687ff" }} />
      </>}
      <p className="field-help">{elapsed != null ? `AI処理の経過 ${duration(elapsed)}` : "AI処理中"}{progress?.remaining_sec != null && progress.phase === "SEPARATING" ? ` · 音源分離の残り約 ${duration(progress.remaining_sec)}` : ""}</p>
      {vocalOnly ? <p className="field-help">{progress?.scan_start_sec != null && progress.scan_end_sec != null ? `確認範囲 ${duration(progress.scan_start_sec)}〜${duration(progress.scan_end_sec)}。` : ""}先頭から順に声を確認し、検出できたら残りの分離を省略します。見つからなければ次の区間を調べます。</p> : <p className="field-help">CPUでの音源分離は1曲に数分かかる場合があります。曲の完了数と、1曲内の音源分離の進捗を別々に表示します。</p>}
    </>}
    <p className="field-help">完了した曲：{job.completed}/{job.total}{job.failed ? ` · 失敗 ${job.failed}曲` : ""}</p>
  </div>;
}
