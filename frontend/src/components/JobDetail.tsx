import { useEffect, useRef, useState } from "react";
import { api, openProgressSocket } from "../api";
import type { Candidate, JobSummary, ProgressEvent } from "../types";
import { CandidateTable } from "./CandidateTable";
import { WritePlanPanel } from "./WritePlanPanel";

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
  const [log, setLog] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

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

  useEffect(() => {
    setJob(null);
    setCandidates([]);
    setLog([]);
    setErr(null);
    refreshJob();

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
      refreshJob();
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div>
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2 style={{ marginBottom: 6 }}>ジョブ詳細</h2>
            <div className="mono muted">{jobId}</div>
          </div>
          <div className="row">
            {job && <span className={`status ${job.status}`}>{job.status}</span>}
            {job && !TERMINAL.has(job.status) && (
              <button className="secondary" onClick={cancel}>
                キャンセル
              </button>
            )}
            <a className="secondary" href={api.reportCsvUrl(jobId)} style={{ textDecoration: "none" }}>
              <button className="secondary">CSV</button>
            </a>
          </div>
        </div>
        {job && (
          <p className="muted" style={{ marginTop: 10 }}>
            進捗 {job.completed}/{job.total}
            {job.failed > 0 ? ` · 失敗 ${job.failed}` : ""}
          </p>
        )}
        {err && <p className="error">{err}</p>}
        {log.length > 0 && (
          <div className="log" style={{ marginTop: 10 }}>
            {log.join("\n")}
          </div>
        )}
      </div>

      <div className="panel">
        <h2>キュー候補</h2>
        <CandidateTable candidates={candidates} onChanged={loadCandidates} />
      </div>

      <WritePlanPanel jobId={jobId} writable={writable} />
    </div>
  );
}
