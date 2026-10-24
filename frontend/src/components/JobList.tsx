import { useState } from "react";
import type { JobSummary } from "../types";
import { jobDate, jobStatus, TERMINAL, trackName } from "../jobs";

export function JobList({ jobs, activeId, onSelect, loading }: {
  jobs: JobSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
}) {
  const [filter, setFilter] = useState("");
  const visible = jobs.filter((j) => `${trackName(j.track_path, j.track_title, j.track_artist)} ${j.track_path ?? ""} ${j.id}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <section className="panel" aria-labelledby="history-title">
      <div className="section-heading"><h2 id="history-title">解析履歴</h2><span className="muted">{jobs.length} 件</span></div>
      {jobs.length > 0 && <input type="search" aria-label="解析履歴を曲名で検索" placeholder="曲名で履歴を検索" value={filter} onChange={(e) => setFilter(e.target.value)} className="history-search" />}
      {loading && jobs.length === 0 ? <p className="field-help" role="status">履歴を読み込んでいます…</p> : jobs.length === 0 ? <p className="field-help">解析した曲がここに並びます。前の解析結果も開き直せます。</p> : visible.length === 0 ? <p className="field-help">該当する履歴はありません。</p> : null}
      <div className="job-history">
        {visible.map((j) => {
          const pct = j.total > 0 ? Math.round(((j.completed + j.failed) / j.total) * 100) : 0;
          const running = !TERMINAL.has(j.status);
          return <button type="button" key={j.id} className={`job ${activeId === j.id ? "active" : ""}`} aria-pressed={activeId === j.id} onClick={() => onSelect(j.id)}>
            <strong className="job-title" title={j.track_path ?? undefined}>{j.total > 1 ? `${j.total}曲の一括解析 · ` : ""}{trackName(j.track_path, j.track_title, j.track_artist)}</strong>
            <div className="row" style={{ justifyContent: "space-between" }}><span className={`status ${j.failed > 0 ? "FAILED" : j.status}`}>{jobStatus(j.status, j.failed)}</span><time className="muted" dateTime={j.created_at}>{jobDate(j.created_at)}</time></div>
            {running && <div className={`progress ${pct === 0 ? "indeterminate" : ""}`}><span style={{ width: `${pct}%` }} /></div>}
          </button>;
        })}
      </div>
    </section>
  );
}
