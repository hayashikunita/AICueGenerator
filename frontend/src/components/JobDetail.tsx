import { useEffect, useMemo, useRef, useState } from "react";
import { api, openProgressSocket } from "../api";
import type { Candidate, CueTarget, JobSummary, JobTrack, ProgressEvent } from "../types";
import { AnalysisSourcePanel } from "./AnalysisSourcePanel";
import { CandidateTable } from "./CandidateTable";
import { Timeline } from "./Timeline";
import { WritePlanPanel } from "./WritePlanPanel";
import { useToast } from "./Toast";
import { jobDate, jobStatus, TERMINAL, trackName } from "../jobs";
import { CueKindSwatch } from "./CueKindSwatch";
import { CUE_TARGETS } from "../cueTargets";
import { ManualCueForm } from "./ManualCueForm";
import { introOutroLabel } from "../introOutro";
import { AnalysisProgress } from "./AnalysisProgress";

export function JobDetail({
  jobId,
  onJobUpdated,
}: {
  jobId: string;
  onJobUpdated: () => void;
}) {
  const [job, setJob] = useState<JobSummary | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [activeTrackId, setActiveTrackId] = useState("");
  const [trackFilter, setTrackFilter] = useState("all");
  const [scopeChoice, setScopeChoice] = useState<"NEW" | "ALL" | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [tracks, setTracks] = useState<JobTrack[]>([]);
  const [log, setLog] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [pendingDecisions, setPendingDecisions] = useState(0);
  const [playbackMs, setPlaybackMs] = useState(0);
  const [manualBusy, setManualBusy] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [seekRequest, setSeekRequest] = useState<{ time_ms: number; sequence: number } | null>(null);
  const seekSequence = useRef(0);
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
      .then((r) => { setTracks(r.tracks); })
      .catch((e) => setErr(`曲の情報を取得できませんでした: ${e}`));
  };

  useEffect(() => {
    let active = true;
    let finished = false;
    setJob(null);
    setCandidates([]);
    setTracks([]);
    setActiveTrackId("");
    setTrackFilter("all");
    setScopeChoice(null);
    setLog([]);
    setErr(null);
    refreshJob();
    loadTracks();

    const ws = openProgressSocket(jobId);
    ws.onmessage = (ev) => {
      if (!active) return;
      const p: ProgressEvent = JSON.parse(ev.data);
      setLog((l) => [...l, `[${p.seq}] ${p.type} ${JSON.stringify(p.data)}`]);
      const terminal = ["JOB_COMPLETED", "JOB_CANCELLED", "JOB_FAILED"].includes(p.type);
      if (terminal && finished) return;
      if (terminal) {
        finished = true;
        window.clearInterval(timer);
      }
      if (p.type === "JOB_PROGRESS") {
        loadTracks();
      } else if (terminal || ["TRACK_STARTED", "TRACK_COMPLETED", "TRACK_FAILED"].includes(p.type)) {
        loadTracks();
        if (p.type !== "TRACK_STARTED") loadCandidates();
        refreshJob();
      }
    };
    ws.onerror = () => setLog((l) => [...l, "[ws] 接続エラー"]);

    // WS 接続前に既に完了しているジョブのために一度読み込む。
    loadCandidates();

    // WebSocket が切断されても進捗と結果を取得できるようにする。
    const timer = window.setInterval(() => {
      api.getJob(jobId).then((next) => {
        if (!active || finished) return;
        setJob(next);
        if (TERMINAL.has(next.status)) {
          finished = true;
          loadTracks();
          loadCandidates();
          onJobUpdated();
          window.clearInterval(timer);
        } else loadTracks();
      }).catch((e) => setErr(String(e)));
    }, 4000);

    return () => {
      active = false;
      window.clearInterval(timer);
      ws.close();
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

  const resume = async () => {
    setResuming(true);
    try {
      const result = await api.resumeJob(jobId);
      toast.push("info", result.resumed ? "完了済みの結果を保持して、未完了の曲から解析を再開しました" : "解析はすでに実行中です");
      refreshJob();
      loadTracks();
    } catch (e) {
      toast.push("error", `再開できませんでした: ${e}`);
    } finally {
      setResuming(false);
    }
  };

  const pct = job && job.total > 0 ? Math.round(((job.completed + job.failed) / job.total) * 100) : 0;
  const running = job ? !TERMINAL.has(job.status) : false;
  const reusedTracks = tracks.filter((track) => track.status === "COMPLETED" && track.analysis?.cached).length;
  const analyzedTracks = tracks.filter((track) => track.status === "COMPLETED" && !track.analysis?.cached).length;
  const configuredCandidates = useMemo(() => candidates.map((candidate) => ({ ...candidate,
    display_label: job?.params?.cue_mode === "INTRO_OUTRO" && job.params.intro_outro ? introOutroLabel(candidate.type as CueTarget, job.params.intro_outro) : undefined,
    preset: job?.params?.cue_settings?.[candidate.type] ?? job?.params?.cue_default })), [candidates, job?.params]);
  const newTracks = useMemo(() => tracks.filter((track) => !track.analysis?.cached), [tracks]);
  const scope = scopeChoice ?? (!running && reusedTracks > 0 && newTracks.length > 0 ? "NEW" : "ALL");
  const groupTracks = scope === "NEW" ? newTracks : tracks;
  const groupIds = useMemo(() => new Set(groupTracks.map((track) => track.id)), [groupTracks]);
  const groupCandidates = useMemo(() => configuredCandidates.filter((candidate) => !candidate.track_id || groupIds.has(candidate.track_id)), [configuredCandidates, groupIds]);
  const scopeLabel = scope === "NEW" ? `今回追加した${newTracks.length}曲` : `全${tracks.length}曲`;
  const scopeKey = `${scope}:${groupTracks.map((track) => track.id).join("|")}`;
  const high = groupCandidates.filter((c) => c.band === "high").length;
  const review = groupCandidates.filter((c) => c.band === "review").length;
  const accepted = groupCandidates.filter((c) => c.accepted === true).length;
  const memoryCount = groupCandidates.filter((c) => c.accepted === true && (c.cue_kind === "MEMORY" || c.cue_kind === "BOTH")).length;
  const hotCount = groupCandidates.filter((c) => c.accepted === true && (c.cue_kind === "HOT" || c.cue_kind === "BOTH")).length;
  const decisionKey = groupCandidates.map((c) => `${c.id}:${c.accepted}:${c.cue_kind}:${c.time_ms}`).join("|");
  const activeTrack = groupTracks.find((track) => track.id === activeTrackId) ?? groupTracks[0];
  const audioUrl = activeTrack?.status === "COMPLETED" ? api.audioUrl(activeTrack.id) : null;
  const multiTrack = tracks.length > 1;
  const trackNames = Object.fromEntries(tracks.map((track) => {
    const name = trackName(track.path, track.title, track.artist);
    const duplicates = tracks.filter((t) => trackName(t.path, t.title, t.artist).toLowerCase() === name.toLowerCase()).length > 1;
    return [track.id, duplicates ? `${name} · ${track.path.split(/[\\/]/).slice(-2, -1)[0] ?? ""} [${track.content_id}]` : name];
  }));
  const effectiveFilter = groupIds.has(trackFilter) ? trackFilter : "all";
  const scopedCandidates = useMemo(() => effectiveFilter === "all" ? groupCandidates : groupCandidates.filter((c) => c.track_id === effectiveFilter), [effectiveFilter, groupCandidates]);
  const audioCandidates = useMemo(() => groupCandidates.filter((c) => !c.track_id || c.track_id === activeTrack?.id), [groupCandidates, activeTrack?.id]);
  const trackLocked = pendingDecisions > 0 || manualBusy || drafting || exportBusy;
  const countsByTrack = new Map<string, { memory: number; hot: number }>();
  for (const c of groupCandidates) if (c.accepted) {
    const id = c.track_id ?? activeTrack?.id ?? "single";
    const counts = countsByTrack.get(id) ?? { memory: 0, hot: 0 };
    if (c.cue_kind === "MEMORY" || c.cue_kind === "BOTH") counts.memory++;
    if (c.cue_kind === "HOT" || c.cue_kind === "BOTH") counts.hot++;
    countsByTrack.set(id, counts);
  }
  const cueCounts = Array.from(countsByTrack, ([trackId, counts]) => ({ trackId, title: trackNames[trackId] ?? trackName(job?.track_path, job?.track_title, job?.track_artist), ...counts }));
  const audition = (time_ms: number, trackId?: string | null) => {
    if (manualBusy || pendingDecisions > 0) return;
    const track = groupTracks.find((t) => t.id === trackId) ?? activeTrack;
    if (!track || track.status !== "COMPLETED") return;
    setActiveTrackId(track.id);
    setPlaybackMs(time_ms);
    setSeekRequest({ time_ms, sequence: ++seekSequence.current });
    document.getElementById("result-timeline")?.scrollIntoView({ block: "nearest" });
  };
  const changeScope = (next: "NEW" | "ALL") => {
    setScopeChoice(next);
    setTrackFilter("all");
    setActiveTrackId("");
    setPlaybackMs(0);
    setSeekRequest(null);
  };

  return (
    <div>
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ marginBottom: 6 }}>解析結果</h2>
            <h3 className="result-title">{job ? job.total > 1 ? `${job.total}曲の解析結果` : trackName(job.track_path, job.track_title, job.track_artist) : "読み込み中…"}</h3>
            <div className="muted" style={{ fontSize: 12 }}>{job ? jobDate(job.created_at) : ""}</div>
            {job && <p className="field-help" role="status">対象 {job.total}曲 · {running ? "新規解析完了" : "新規解析"} {analyzedTracks}曲 · 解析済み {reusedTracks}曲を再利用</p>}
            {job?.params && job.params.cue_mode !== "INTRO_OUTRO" && <p className="field-help">解析単位：{job.params.beats_per_phrase ?? (job.params.bars_per_phrase ?? 16) * 4} Beat（{(job.params.beats_per_phrase ?? (job.params.bars_per_phrase ?? 16) * 4) / 4} 小節）</p>}
            {job?.params?.analysis_quality === "AI" && <p className="field-help">判定方法：AI補助（{job.params.ai_scope === "VOCAL" ? "ボーカルを検出" : "PC内で音源分離"}）</p>}
            {job?.params?.legacy_vocal_start && <p className="field-help">従来の候補＋歌い始め</p>}
            {job?.params?.legacy_vocal_end && <p className="field-help">従来の候補＋ボーカルの終わり</p>}
            {!!job?.params?.cue_targets?.length && <p className="field-help">指定位置：{job.params.cue_targets.map((target) => CUE_TARGETS.find((option) => option.value === target)?.label ?? target).join("・")}</p>}
            {job?.params?.cue_mode === "INTRO_OUTRO" && job.params.intro_outro && <p className="field-help">イントロアウトロ特化：{job.params.intro_outro.targets.map((target) => introOutroLabel(target, job.params!.intro_outro!)).join("・")}</p>}
          </div>
          <div className="row">
            {job && <span className={`status ${job.failed > 0 ? "FAILED" : job.status}`}>{job.can_resume ? "中断（再開できます）" : jobStatus(job.status, job.failed)}</span>}
            {job?.can_resume && <button className="secondary tiny" onClick={resume} disabled={resuming}>{resuming ? "再開中…" : "未完了の曲から再開"}</button>}
            {job && !TERMINAL.has(job.status) && !job.can_resume && (
              <button className="secondary tiny" onClick={cancel} disabled={cancelling}>
                {cancelling ? "停止中…" : "解析をキャンセル"}
              </button>
            )}
            <button className="secondary tiny" disabled={downloading || !groupCandidates.length || !groupTracks.length} onClick={async () => { setDownloading(true); try { await api.downloadReport(jobId, groupTracks.map((track) => track.id)); } catch (e) { toast.push("error", String(e)); } finally { setDownloading(false); } }}>{downloading ? "取得中…" : "CSV を保存"}</button>
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
            <div className="stat-label">完了した曲</div>
          </div>
          <div className="stat">
            <div className="stat-val">{groupCandidates.length}</div>
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

        {running && job && (job.can_resume
          ? <p className="field-help" role="status">解析が中断しています。完了した{job.completed}曲の結果は保存されています。「未完了の曲から再開」で続きを解析できます。</p>
          : <AnalysisProgress job={job} tracks={tracks} />)}
        {!running && tracks.length > 0 && <div className="result-scope" aria-label="確認・書き出しの対象">
          <div className="source-switch">
            <button type="button" className={scope === "NEW" ? "" : "secondary"} aria-pressed={scope === "NEW"} disabled={trackLocked || newTracks.length === 0} onClick={() => changeScope("NEW")}>今回追加した{newTracks.length}曲</button>
            <button type="button" className={scope === "ALL" ? "" : "secondary"} aria-pressed={scope === "ALL"} disabled={trackLocked} onClick={() => changeScope("ALL")}>全{tracks.length}曲</button>
          </div>
          <p className="field-help" role="status">確認・書き出し対象：{scopeLabel}。候補の確認、XML・CSVの書き出しに共通です。</p>
          {newTracks.length === 0 && <p className="field-help">今回は全曲が保存済みのため、「全曲」で結果を表示しています。</p>}
          {trackLocked && <p className="field-help">保存・書き出し中の処理、または位置の調整を完了・破棄すると対象を切り替えられます。</p>}
        </div>}
        {multiTrack && <div className="batch-results" aria-label="曲ごとの解析結果">
          <div className="section-heading"><h3>確認する曲</h3><button type="button" className="secondary tiny" aria-pressed={effectiveFilter === "all"} disabled={trackLocked} onClick={() => setTrackFilter("all")}>全曲の候補を表示</button></div>
          <p className="field-help">曲を選ぶと試聴と候補が切り替わります。全曲表示からも候補の「試聴」で対象曲を再生できます。</p>
          <div className="batch-result-list">{groupTracks.map((track) => {
            const own = groupCandidates.filter((c) => c.track_id === track.id);
            return <button type="button" key={track.id} className={`secondary result-track ${effectiveFilter === track.id ? "selected" : ""}`} aria-pressed={effectiveFilter === track.id} disabled={trackLocked} onClick={() => { setActiveTrackId(track.id); setTrackFilter(track.id); setPlaybackMs(0); setSeekRequest(null); }}>
              <strong>{trackNames[track.id]}</strong><span>{track.analysis?.cached ? "解析済みを再利用" : jobStatus(track.status, track.status === "FAILED" ? 1 : 0)} · 候補 {own.length} · 採用 {own.filter((c) => c.accepted).length}</span>{track.analysis?.reason && <span className="error">{track.analysis.reason}</span>}
            </button>;
          })}</div>
          {trackLocked && <p className="field-help" role="status">保存中の処理、または位置の調整を完了・破棄すると曲を切り替えられます。</p>}
        </div>}
        {activeTrack && <AnalysisSourcePanel track={activeTrack} />}
        {job && job.failed > 0 && <p className="error" role="alert">{job.failed} 曲を解析できませんでした。上の理由と、音源・rekordbox の解析状態を確認してください。</p>}
        {running && !job?.can_resume && <p className="field-help" role="status">音源を解析しています。完了するとキュー候補が自動で表示されます。</p>}

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

      {(groupCandidates.length > 0 || audioUrl) && (
        <div className="panel" id="result-timeline">
          <h2>タイムライン{multiTrack && activeTrack ? `：${trackNames[activeTrack.id]}` : ""}</h2>
          <Timeline key={`timeline-${activeTrack?.id ?? "empty"}`} candidates={audioCandidates} audioUrl={audioUrl} seekRequest={seekRequest} onPositionChange={setPlaybackMs} />
          {!running && activeTrack?.status === "COMPLETED" && <ManualCueForm key={`manual-${activeTrack.id}`} jobId={jobId} trackId={activeTrack.id} currentTimeMs={playbackMs} disabled={pendingDecisions > 0 || drafting || exportBusy} onBusy={setManualBusy} onAdded={async () => { await Promise.all([loadCandidates(), loadTracks()]); }} />}
        </div>
      )}

      <div className="panel">
        <h2>2. キュー候補を確認・採用 <span className="muted">（採用 {accepted} 候補）</span></h2>
        <div className="cue-kind-counts" aria-live="polite"><span><CueKindSwatch kind="MEMORY" />Memory Cue <b>{memoryCount}</b> 件</span><span><CueKindSwatch kind="HOT" />Hot Cue <b>{hotCount}</b> 件</span></div>
        <CandidateTable key={`${scopeKey}:${effectiveFilter}`} jobId={!running ? jobId : undefined} candidates={scopedCandidates} trackNames={multiTrack ? trackNames : undefined} onBatchChanged={setCandidates} onChanged={(id, accepted, cueKind, position) => {
          setCandidates((current) => current.map((c) => c.id === id ? { ...c, accepted, cue_kind: cueKind, original_time_ms: c.original_time_ms ?? c.time_ms, time_ms: position.time_ms, beat: position.beat } : c));
        }} onSavingChange={(delta) => setPendingDecisions((n) => n + delta)} disabled={manualBusy || exportBusy} onDraftChange={setDrafting} onAudition={tracks.some((t) => t.status === "COMPLETED") ? audition : undefined} />
      </div>

      <WritePlanPanel key={`${scopeKey}:${decisionKey}`} jobId={jobId} acceptedCount={accepted} memoryCount={memoryCount} hotCount={hotCount} cueCounts={cueCounts} trackNames={Object.fromEntries(groupTracks.map((track) => [track.id, trackNames[track.id]]))} candidates={groupCandidates} trackIds={groupTracks.map((track) => track.id)} scopeLabel={scopeLabel} onBusyChange={setExportBusy} onAudition={tracks.some((track) => track.status === "COMPLETED") ? audition : undefined} deciding={pendingDecisions > 0 || manualBusy || running || drafting} />
    </div>
  );
}
