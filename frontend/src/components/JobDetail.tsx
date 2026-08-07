import { useEffect, useRef, useState } from "react";
import { api, openProgressSocket } from "../api";
import type { Candidate, JobSummary, ProgressEvent } from "../types";
import { CandidateTable } from "./CandidateTable";
import { Timeline } from "./Timeline";
import { WritePlanPanel } from "./WritePlanPanel";
import { useToast } from "./Toast";

const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

export function JobDetail({
  jobId,
  writable,
  onJobUpdated,
}: {
  jobId: string;
  writable: boolean;
  onJobUpdated: () => void;
}) {
  const [job, setJob] = useState<JobSummary | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const toast = useToast();

  const refreshJob = () => {
    api.getJob(jobId).then(setJob).catch((e) => setErr(String(e)));
    onJobUpdated();
  };

  const loadCandidates = () => {
    api
      .candidates(jobId)
      .then((r) => setCandidates(r.candidates))
      .catch((e) => setErr(String(e)));
  };

  const loadTracks = () => {
    api
      .jobTracks(jobId)
      .then((r) => setAudioUrl(r.tracks.length > 0 ? api.audioUrl(r.tracks[0].id) : null))
      .catch(() => setAudioUrl(null));
  };

  useEffect(() => {
    setJob(null);
    setCandidates([]);
    setAudioUrl(null);
    setLog([]);
    setErr(null);
    refreshJob();
    loadTracks();

    const ws = openProgressSocket(jobId);
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      const p: ProgressEvent = JSON.parse(ev.data);
      setLog((l) => [...l, `[${p.seq}] ${p.type} ${JSON.stringify(p.data)}`]);
      if (p.type === "TRACK_COMPLETED" || p.type === "JOB_COMPLETED") {
        loadCandidates();
        refreshJob();
      }
      if (["JOB_COMPLETED", "JOB_CANCELLED", "JOB_FAILED"].includes(p.type)) {
        refreshJob();
      }
    };
    ws.onerror = () => setLog((l) => [...l, "[ws] 接続エラー"]);

    // WS 接続前に既に完了しているジョブのために一度読み込む。
    loadCandidates();

    return () => {
      ws.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const cancel = async () => {
    try {
      await api.cancelJob(jobId);
      toast.push("info", "ジョブをキャンセルしました");
      refreshJob();
    } catch (e) {
      toast.push("error", `キャンセル失敗: ${e}`);
    }
  };

  const pct = job && job.total > 0 ? Math.round((job.completed / job.total) * 100) : 0;
  const running = job ? !TERMINAL.has(job.status) : false;
  const high = candidates.filter((c) => c.band === "high").length;
  const review = candidates.filter((c) => c.band === "review").length;

  return (
    <div>
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ marginBottom: 6 }}>ジョブ詳細</h2>
            <div className="mono muted" style={{ fontSize: 12 }}>{jobId}</div>
          </div>
          <div className="row">
            {job && <span className={`status ${job.status}`}>{job.status}</span>}
            {job && !TERMINAL.has(job.status) && (
              <button className="secondary tiny" onClick={cancel}>
                キャンセル
              </button>
            )}
            <a href={api.reportCsvUrl(jobId)} style={{ textDecoration: "none" }}>
              <button className="secondary tiny">CSV ⭳</button>
            </a>
          </div>
        </div>

        {job && (
          <div className={`progress ${running && pct === 0 ? "indeterminate" : ""}`} style={{ marginTop: 14 }}>
            <span style={{ width: `${pct}%` }} />
          </div>
        )}

        <div className="stats" style={{ marginTop: 14 }}>
          <div className="stat">
            <div className="stat-val">{job ? `${job.completed}/${job.total}` : "—"}</div>
            <div className="stat-label">進捗</div>
          </div>
          <div className="stat">
            <div className="stat-val">{candidates.length}</div>
            <div className="stat-label">候補</div>
          </div>
          <div className="stat">
            <div className="stat-val" style={{ color: "var(--high)" }}>{high}</div>
            <div className="stat-label">High</div>
          </div>
          <div className="stat">
            <div className="stat-val" style={{ color: "var(--review)" }}>{review}</div>
            <div className="stat-label">Review</div>
          </div>
          {job && job.failed > 0 && (
            <div className="stat">
              <div className="stat-val" style={{ color: "var(--reject)" }}>{job.failed}</div>
              <div className="stat-label">失敗</div>
            </div>
          )}
        </div>

        {err && <p className="error">{err}</p>}

        {log.length > 0 && (
          <>
            <button
              className="secondary tiny"
              style={{ marginTop: 12 }}
              onClick={() => setShowLog((s) => !s)}
            >
              {showLog ? "ログを隠す" : `進捗ログを表示 (${log.length})`}
            </button>
            {showLog && (
              <div className="log" style={{ marginTop: 10 }}>
                {log.join("\n")}
              </div>
            )}
          </>
        )}
      </div>

      {candidates.length > 0 && (
        <div className="panel">
          <h2>タイムライン</h2>
          <Timeline candidates={candidates} audioUrl={audioUrl} />
        </div>
      )}

      <div className="panel">
        <h2>キュー候補</h2>
        <CandidateTable candidates={candidates} onChanged={loadCandidates} />
      </div>

      <WritePlanPanel jobId={jobId} writable={writable} />
    </div>
  );
}
