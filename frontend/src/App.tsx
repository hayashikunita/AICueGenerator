import { useCallback, useEffect, useState } from "react";
import { api, token } from "./api";
import { CueColorSettings } from "./components/CueColorSettings";
import { Diagnostics } from "./components/Diagnostics";
import { JobDetail } from "./components/JobDetail";
import { JobList } from "./components/JobList";
import { NewJobForm } from "./components/NewJobForm";
import type { JobSummary } from "./types";
import { TERMINAL } from "./jobs";

export function App() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [jobsError, setJobsError] = useState("");
  const [loading, setLoading] = useState(true);

  const refreshJobs = useCallback(() => {
    if (!token) return;
    api
      .listJobs()
      .then((r) => {
        setJobs(r.jobs);
        setJobsError("");
      })
      .catch((e) => setJobsError(`履歴を取得できませんでした: ${e}`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (!jobs.some((j) => !TERMINAL.has(j.status))) return;
    const timer = window.setInterval(refreshJobs, 4000);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

  useEffect(() => {
    if (activeId && window.matchMedia("(max-width: 800px)").matches) {
      document.getElementById("analysis-result")?.scrollIntoView({ block: "start" });
    }
  }, [activeId]);

  if (!token) {
    return (
      <div className="app">
        <header className="app-header">
          <div className="logo" aria-hidden="true">CUE</div>
          <div>
            <h1>rekordbox AI Cue Generator</h1>
            <p className="sub">EDM 楽曲を解析し、Drop / Break / Build などのキュー候補を提案します。</p>
          </div>
        </header>
        <div className="panel error">
          トークンがありません。起動時に表示された URL（?token=…付き）でアクセスしてください。
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="logo" aria-hidden="true">CUE</div>
        <div>
          <h1>rekordbox AI Cue Generator</h1>
          <p className="sub">rekordbox 解析済みグリッド → 候補を試聴 → MEMORY / HOT CUE</p>
        </div>
      </header>

      <nav className="workflow" aria-label="使い方">
        <span><b>1</b> 曲を選んで解析</span><span><b>2</b> 試聴してキューを採用</span><span><b>3</b> rekordbox へ書き出し</span>
      </nav>
      <Diagnostics />

      {jobsError && <div className="error row" role="alert"><span>{jobsError}</span><button className="secondary tiny" onClick={refreshJobs}>再試行</button></div>}

      <div className="grid">
        <div>
          <NewJobForm
            historyKey={jobs.filter((job) => TERMINAL.has(job.status)).map((job) => `${job.id}:${job.updated_at}`).join("|")}
            onCreated={(id) => {
              refreshJobs();
              setActiveId(id);
            }}
          />
          <JobList jobs={jobs} activeId={activeId} onSelect={setActiveId} loading={loading} />
          <CueColorSettings />
        </div>
        <div id="analysis-result" className="analysis-result">
          {activeId ? (
            <JobDetail key={activeId} jobId={activeId} onJobUpdated={refreshJobs} />
          ) : (
            <div className="panel">
              <div className="empty">
                <span className="emoji">🎚️</span>
                <h3>曲の展開を、キューに。</h3>
                <p>曲を選んで解析すると、Intro・Break・Build・Drop・Outro の候補が表示されます。</p>
                <p>音源を試聴し、使いたい候補を採用して rekordbox へ書き出しましょう。</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
