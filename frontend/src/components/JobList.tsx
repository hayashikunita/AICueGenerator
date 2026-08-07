import type { JobSummary } from "../types";

const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

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
      {jobs.length === 0 && (
        <div className="empty">
          <span className="emoji">📭</span>
          まだジョブがありません。
        </div>
      )}
      {jobs.map((j) => {
        const pct = j.total > 0 ? Math.round((j.completed / j.total) * 100) : 0;
        const running = !TERMINAL.has(j.status);
        return (
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
            <div className={`progress ${running && pct === 0 ? "indeterminate" : ""}`}>
              <span style={{ width: `${pct}%` }} />
            </div>
            <div
              className="row"
              style={{ justifyContent: "space-between", alignItems: "center", marginTop: 8 }}
            >
              <span className="mono" style={{ fontSize: 11 }}>
                {j.id.slice(0, 14)}…
              </span>
              <button
                type="button"
                className="secondary tiny"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(j.id);
                }}
              >
                開く
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
