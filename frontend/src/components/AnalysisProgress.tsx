import { useEffect, useRef, useState } from "react";
import type { JobSummary, JobTrack } from "../types";
import { trackName } from "../jobs";
import { vocalCoverage } from "../analysisProgress";

function duration(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

export function AnalysisProgress({ job, tracks }: { job: JobSummary; tracks: JobTrack[] }) {
  const [now, setNow] = useState(Date.now());
  const furthest = useRef({ key: "", seconds: 0 });
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const track = tracks.find((item) => item.status === "RUNNING");
  if (!track) return <p className="field-help" role="status">解析の開始を待っています。完了した曲：{job.completed}/{job.total}</p>;
  const data = track.analysis;
  const progress = data?.ai_progress;
  const vocalOnly = data?.ai_scope === "VOCAL" || progress?.scope === "VOCAL";
  const coverage = vocalOnly ? vocalCoverage(data, track.duration_ms) : null;
  if (coverage) {
    const key = `${job.id}:${track.id}`;
    coverage.seconds = Math.min(coverage.total, Math.max(coverage.seconds, furthest.current.key === key ? furthest.current.seconds : 0));
    coverage.percent = Math.floor(coverage.seconds / coverage.total * 100);
    furthest.current = { key, seconds: coverage.seconds };
  }
  const ai = job.params?.analysis_quality === "AI" && data?.analysis_quality === "AI";
  const start = data?.ai_started_at ? Date.parse(data.ai_started_at) : NaN;
  const elapsed = Number.isFinite(start) ? Math.max(0, (now - start) / 1000) : progress?.elapsed_sec;
  const index = tracks.findIndex((item) => item.id === track.id) + 1;
  return <div className="analysis-progress-info" aria-label="処理中の曲の進捗">
    <strong>{index}/{job.total}曲目：{trackName(track.path, track.title, track.artist)}</strong>
    <p role="status">{data?.stage || "音源の特徴を解析しています。"}</p>
    {ai && <>
      {vocalOnly && coverage && <>
        <p>確認済み：{duration(coverage.seconds)}／{duration(coverage.total)}（{coverage.percent}%）</p>
        <progress aria-label="曲内の確認済み範囲" max={coverage.total} value={coverage.seconds} style={{ width: "100%", accentColor: "#1687ff" }} />
      </>}
      {vocalOnly && progress?.scan_start_sec != null && progress.scan_end_sec != null && <p>現在の確認範囲：{duration(progress.scan_start_sec)}〜{duration(progress.scan_end_sec)}{progress.percent != null ? ` · 区間内の分離 ${progress.percent}%` : " · 準備中"}</p>}
      {!vocalOnly && progress?.percent != null && <>
        <p>この曲の音源分離：{progress.percent}%</p>
        <progress aria-label="この曲の音源分離" max="100" value={progress.percent} style={{ width: "100%", accentColor: "#1687ff" }} />
      </>}
      <p className="field-help">{elapsed != null ? `AI処理の経過 ${duration(elapsed)}` : "AI処理中"}{progress?.remaining_sec != null && progress.phase === "SEPARATING" ? ` · ${vocalOnly ? "現在の区間" : "音源分離"}の残り約 ${duration(progress.remaining_sec)}` : ""}</p>
      {vocalOnly ? <p className="field-help">曲末までの有限の範囲を順に確認しています。区間内の％は次の範囲に進むと0へ戻りますが、上の「確認済み」は戻りません。{data?.vocal_end_requested || job.params?.legacy_vocal_end || job.params?.cue_targets?.includes("VOCAL_END") || job.params?.intro_outro?.targets.includes("VOCAL_END") ? "ボーカルの終わりを探すため、歌い始めを検出しても曲末まで解析を続けます。" : "継続する声を確認できたら残りを省略し、判断できない場合も曲末で終了します。"}</p> : <p className="field-help">CPUでの音源分離は1曲に数分かかる場合があります。曲の完了数と、1曲内の音源分離の進捗を別々に表示します。</p>}
    </>}
    <p className="field-help">完了した曲：{job.completed}/{job.total}{job.failed ? ` · 失敗 ${job.failed}曲` : ""}</p>
  </div>;
}
