import type { JobSummary } from "../types";

export function JobList({
  jobs,
  activeId,
  onSelect,
}: {
  jobs: JobSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="panel">
      <h2>ジョブ一覧</h2>
      {jobs.length === 0 && <p className="muted">まだジョブがありません。</p>}
      {jobs.map((j) => (
        <div
          key={j.id}
          className={`job ${activeId === j.id ? "active" : ""}`}
          onClick={() => onSelect(j.id)}
        >
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className={`status ${j.status}`}>{j.status}</span>
            <span className="mono muted">
              {j.completed}/{j.total}
              {j.failed > 0 ? ` · 失敗${j.failed}` : ""}
            </span>
          </div>
          <div className="mono" style={{ marginTop: 6 }}>
            {j.id.slice(0, 12)}…
          </div>
        </div>
      ))}
    </div>
  );
}
