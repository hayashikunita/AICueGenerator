import { useCallback, useEffect, useState } from "react";
import { api, token } from "./api";
import { Diagnostics } from "./components/Diagnostics";
import { JobDetail } from "./components/JobDetail";
import { JobList } from "./components/JobList";
import { NewJobForm } from "./components/NewJobForm";
import type { JobSummary } from "./types";

export function App() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [writable, setWritable] = useState(false);

  const refreshJobs = useCallback(() => {
    api
      .listJobs()
      .then((r) => setJobs(r.jobs))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshJobs();
    api
      .diagnostics()
      .then((d) => setWritable(d.writable))
      .catch(() => {});
  }, [refreshJobs]);

  if (!token) {
    return (
      <div className="app">
        <h1>rekordbox AI Cue Generator</h1>
        <div className="panel error">
          トークンがありません。起動時に表示された URL（?token=…付き）でアクセスしてください。
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <h1>rekordbox AI Cue Generator</h1>
      <p className="sub">EDM 楽曲を解析し、Drop / Break / Build などのキュー候補を提案します。</p>

      <Diagnostics />

      <div className="grid">
        <div>
          <NewJobForm
            onCreated={(id) => {
              refreshJobs();
              setActiveId(id);
            }}
          />
          <JobList jobs={jobs} activeId={activeId} onSelect={setActiveId} />
        </div>
        <div>
          {activeId ? (
            <JobDetail jobId={activeId} writable={writable} onJobUpdated={refreshJobs} />
          ) : (
            <div className="panel muted">左のジョブを選択するか、新規解析を開始してください。</div>
          )}
        </div>
      </div>
    </div>
  );
}
