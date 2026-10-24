import { useEffect, useRef, useState } from "react";
import { api, openProgressSocket } from "../api";
import type { Candidate, JobSummary, JobTrack, ProgressEvent } from "../types";
import { AnalysisSourcePanel } from "./AnalysisSourcePanel";
import { CandidateTable } from "./CandidateTable";
import { Timeline } from "./Timeline";
import { WritePlanPanel } from "./WritePlanPanel";
import { useToast } from "./Toast";
import { jobDate, jobStatus, TERMINAL, trackName } from "../jobs";
import { CueKindSwatch } from "./CueKindSwatch";
import { CUE_TARGETS } from "../cueTargets";
import { ManualCueForm } from "./ManualCueForm";

export function JobDetail({
  jobId,
  onJobUpdated,
}: {
  jobId: string;
  onJobUpdated: () => void;
}) {
  const [job, setJob] = useState<JobSummary | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [tracks, setTracks] = useState<JobTrack[]>([]);
  const [log, setLog] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [pendingDecisions, setPendingDecisions] = useState(0);
  const [playbackMs, setPlaybackMs] = useState(0);
  const [manualBusy, setManualBusy] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [seekRequest, setSeekRequest] = useState<{ time_ms: number; sequence: number } | null>(null);
  const seekSequence = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const toast = useToast();

  const refreshJob = () => {
    api.getJob(jobId).then(setJob).catch((e) => setErr(String(e)));
    onJobUpdated();
  };

  const loadCandidates = () => {
    return api
      .candidates(jobId)
      .then((r) => setCandidates(r.candidates))
      .catch((e) => setErr(String(e)));
  };

  const loadTracks = () => {
    return api
      .jobTracks(jobId)
      .then((r) => { setTracks(r.tracks); setAudioUrl(r.tracks.length > 0 ? api.audioUrl(r.tracks[0].id) : null); })
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
        loadTracks();
        loadCandidates();
        refreshJob();
      }
      if (["JOB_COMPLETED", "JOB_CANCELLED", "JOB_FAILED"].includes(p.type)) {
        loadTracks();
        refreshJob();
      }
    };
    ws.onerror = () => setLog((l) => [...l, "[ws] 接続エラー"]);

    // WS 接続前に既に完了しているジョブのために一度読み込む。
    loadCandidates();

    // WebSocket が切断されても進捗と結果を取得できるようにする。
    const timer = window.setInterval(() => {
      api.getJob(jobId).then((next) => {
        setJob(next);
        if (TERMINAL.has(next.status)) {
          loadTracks();
          loadCandidates();
          onJobUpdated();
          window.clearInterval(timer);
        }
      }).catch((e) => setErr(String(e)));
    }, 4000);

    return () => {
      window.clearInterval(timer);
      ws.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const cancel = async () => {
    setCancelling(true);
    try {
      const result = await api.cancelJob(jobId);
      toast.push("info", result.cancelled ? "解析のキャンセルを受け付けました" : "この解析はすでに終了しています");
      refreshJob();
    } catch (e) {
      toast.push("error", `キャンセル失敗: ${e}`);
    } finally {
      setCancelling(false);
    }
  };

  const pct = job && job.total > 0 ? Math.round(((job.completed + job.failed) / job.total) * 100) : 0;
  const running = job ? !TERMINAL.has(job.status) : false;
  const high = candidates.filter((c) => c.band === "high").length;
  const review = candidates.filter((c) => c.band === "review").length;
  const accepted = candidates.filter((c) => c.accepted === true).length;
  const memoryCount = candidates.filter((c) => c.accepted === true && (c.cue_kind === "MEMORY" || c.cue_kind === "BOTH")).length;
  const hotCount = candidates.filter((c) => c.accepted === true && (c.cue_kind === "HOT" || c.cue_kind === "BOTH")).length;
  const decisionKey = candidates.map((c) => `${c.id}:${c.accepted}:${c.cue_kind}:${c.time_ms}`).join("|");

  return (
    <div>
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ marginBottom: 6 }}>解析結果</h2>
            <h3 className="result-title">{job ? trackName(job.track_path) : "読み込み中…"}</h3>
            <div className="muted" style={{ fontSize: 12 }}>{job ? jobDate(job.created_at) : ""}</div>
            {job?.params && <p className="field-help">解析単位：{job.params.beats_per_phrase ?? (job.params.bars_per_phrase ?? 16) * 4} Beat（{(job.params.beats_per_phrase ?? (job.params.bars_per_phrase ?? 16) * 4) / 4} 小節）</p>}
            {!!job?.params?.cue_targets?.length && <p className="field-help">指定位置：{job.params.cue_targets.map((target) => CUE_TARGETS.find((option) => option.value === target)?.label ?? target).join("・")}</p>}
          </div>
          <div className="row">
            {job && <span className={`status ${job.failed > 0 ? "FAILED" : job.status}`}>{jobStatus(job.status, job.failed)}</span>}
            {job && !TERMINAL.has(job.status) && (
              <button className="secondary tiny" onClick={cancel} disabled={cancelling}>
                {cancelling ? "停止中…" : "解析をキャンセル"}
              </button>
            )}
            <button className="secondary tiny" disabled={downloading || !candidates.length} onClick={async () => { setDownloading(true); try { await api.downloadReport(jobId); } catch (e) { toast.push("error", String(e)); } finally { setDownloading(false); } }}>{downloading ? "取得中…" : "CSV を保存"}</button>
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
            <div className="stat-label">信頼度が高い</div>
          </div>
          <div className="stat">
            <div className="stat-val" style={{ color: "var(--review)" }}>{review}</div>
            <div className="stat-label">要確認</div>
          </div>
          {job && job.failed > 0 && (
            <div className="stat">
              <div className="stat-val" style={{ color: "var(--reject)" }}>{job.failed}</div>
              <div className="stat-label">失敗</div>
            </div>
          )}
        </div>

        {tracks.map((track) => <AnalysisSourcePanel key={track.id} track={track} />)}
        {job && job.failed > 0 && <p className="error" role="alert">{job.failed} 曲を解析できませんでした。上の理由と、音源・rekordbox の解析状態を確認してください。</p>}
        {running && <p className="field-help" role="status">音源を解析しています。完了するとキュー候補が自動で表示されます。</p>}

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

      {(candidates.length > 0 || audioUrl) && (
        <div className="panel">
          <h2>タイムライン</h2>
          <Timeline candidates={candidates} audioUrl={audioUrl} seekRequest={seekRequest} onPositionChange={setPlaybackMs} />
          {job?.status === "COMPLETED" && tracks[0] && <ManualCueForm key={tracks[0].id} jobId={jobId} trackId={tracks[0].id} currentTimeMs={playbackMs} disabled={pendingDecisions > 0 || drafting} onBusy={setManualBusy} onAdded={async () => { await Promise.all([loadCandidates(), loadTracks()]); }} />}
        </div>
      )}

      <div className="panel">
        <h2>2. キュー候補を確認・採用 <span className="muted">（採用 {accepted} 候補）</span></h2>
        <div className="cue-kind-counts" aria-live="polite"><span><CueKindSwatch kind="MEMORY" />Memory Cue <b>{memoryCount}</b> 件</span><span><CueKindSwatch kind="HOT" />Hot Cue <b>{hotCount}</b> 件</span></div>
        <CandidateTable candidates={candidates} onChanged={(id, accepted, cueKind, position) => {
          setCandidates((current) => current.map((c) => c.id === id ? { ...c, accepted, cue_kind: cueKind, original_time_ms: c.original_time_ms ?? c.time_ms, time_ms: position.time_ms, beat: position.beat } : c));
        }} onSavingChange={(delta) => setPendingDecisions((n) => n + delta)} disabled={manualBusy} onDraftChange={setDrafting} onAudition={audioUrl ? (time_ms) => setSeekRequest({ time_ms, sequence: ++seekSequence.current }) : undefined} />
      </div>

      <WritePlanPanel key={decisionKey} jobId={jobId} acceptedCount={accepted} memoryCount={memoryCount} hotCount={hotCount} deciding={pendingDecisions > 0 || manualBusy} />
    </div>
  );
}
