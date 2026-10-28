import type {
  Candidate,
  CollectionXml,
  ExportMode,
  AnalysisInfo,
  AiStatus,
  GridPreview,
  GridPlan,
  CuePosition,
  CueTarget,
  Diagnostics,
  DecisionRequest,
  ExecuteResult,
  ExportXmlResult,
  JobParams,
  JobPreview,
  JobSummary,
  JobTrack,
  RekordboxSearchResult,
  RekordboxPlaylistListResult,
  RekordboxPlaylistTracksResult,
  TrackInput,
  WritePlan,
} from "./types";

// 起動ごとのトークンは URL の ?token= で受け取り localStorage に保持する。
function resolveToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem("aicue_token", fromUrl);
    return fromUrl;
  }
  return localStorage.getItem("aicue_token") ?? "";
}

export const token = resolveToken();

const BASE = "/api/v1";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  }).catch(() => { throw new Error("アプリに接続できません。起動していることを確認し、もう一度お試しください。"); });
  if (!res.ok) {
    const body = await res.text();
    let message = "処理を完了できませんでした。もう一度お試しください。";
    try {
      const detail = JSON.parse(body).detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) message = "入力内容を確認して、もう一度お試しください。";
    } catch { /* A proxy may return HTML instead of an API error. */ }
    if (res.status === 401) message = "認証が切れています。アプリ起動時のURLから開き直してください。";
    throw new Error(message);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  diagnostics: () => req<Diagnostics>("/diagnostics"),
  aiStatus: () => req<AiStatus>("/analysis/ai-status"),

  createJob: (params: JobParams, tracks: TrackInput[]) =>
    req<{ job_id: string }>("/jobs", {
      method: "POST",
      body: JSON.stringify({ params, tracks }),
    }),

  previewJob: (params: JobParams, tracks: TrackInput[], signal?: AbortSignal) =>
    req<JobPreview>("/jobs/preview", {
      method: "POST", body: JSON.stringify({ params, tracks }), signal,
    }),

  listJobs: () => req<{ jobs: JobSummary[] }>("/jobs"),

  getJob: (id: string) => req<JobSummary>(`/jobs/${id}`),

  cancelJob: (id: string) =>
    req<{ cancelled: boolean }>(`/jobs/${id}/cancel`, { method: "POST" }),

  resumeJob: (id: string) =>
    req<{ resumed: boolean }>(`/jobs/${id}/resume`, { method: "POST" }),

  candidates: (jobId: string) =>
    req<{ candidates: Candidate[] }>(`/jobs/${jobId}/candidates`),

  jobTracks: (jobId: string) =>
    req<{ tracks: JobTrack[] }>(`/jobs/${jobId}/tracks`),

  audioUrl: (trackId: string) =>
    `${BASE}/tracks/${trackId}/audio?token=${encodeURIComponent(token)}`,

  searchRekordbox: (query: string, limit = 20) =>
    req<RekordboxSearchResult>(
      `/rekordbox/tracks?query=${encodeURIComponent(query)}&limit=${limit}`,
    ),

  rekordboxPlaylists: () => req<RekordboxPlaylistListResult>("/rekordbox/playlists"),

  rekordboxAnalysis: (id: string, path: string) => req<AnalysisInfo>(`/rekordbox/tracks/${encodeURIComponent(id)}/analysis?path=${encodeURIComponent(path)}`),

  gridPreview: (id: string, path: string) => req<GridPreview>(`/rekordbox/tracks/${encodeURIComponent(id)}/grid?path=${encodeURIComponent(path)}`),

  libraryAudioUrl: (id: string, path: string) => `${BASE}/rekordbox/tracks/${encodeURIComponent(id)}/audio?path=${encodeURIComponent(path)}&token=${encodeURIComponent(token)}`,

  gridPlan: (id: string, path: string, firstBeat: number) => req<GridPlan>(`/rekordbox/tracks/${encodeURIComponent(id)}/grid/plan`, {
    method: "POST", body: JSON.stringify({ path, first_beat: firstBeat }),
  }),

  gridApply: (id: string, planId: string) => req<{ ok: boolean; message: string; backup_dir: string }>(`/rekordbox/tracks/${encodeURIComponent(id)}/grid/apply`, {
    method: "POST", body: JSON.stringify({ plan_id: planId }),
  }),

  rekordboxPlaylistTracks: (id: string, query = "", offset = 0) =>
    req<RekordboxPlaylistTracksResult>(`/rekordbox/playlists/${encodeURIComponent(id)}/tracks?query=${encodeURIComponent(query)}&offset=${offset}&limit=50`),

  decide: (candidateId: string, body: DecisionRequest) =>
    req<{ decision_id: string; candidate_id: string; time_ms?: number; beat?: number | null }>(
      `/candidates/${candidateId}/decision`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  previewPosition: (candidateId: string, timeMs: number, snapTo: "BEAT" | "BAR", step = 0) =>
    req<CuePosition>(`/candidates/${encodeURIComponent(candidateId)}/preview-position`, { method: "POST", body: JSON.stringify({ time_ms: timeMs, snap_to: snapTo, step }) }),

  acceptCandidates: (jobId: string, candidateIds: string[], cueKind: "MEMORY" | "HOT" | "BOTH" | "PRESET") =>
    req<{ candidates: Candidate[] }>(`/jobs/${encodeURIComponent(jobId)}/candidates/accept`, { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds, cue_kind: cueKind }) }),

  addManualCandidate: (jobId: string, trackId: string, target: CueTarget, timeMs: number, snapTo: "BEAT" | "BAR") =>
    req<Candidate>(`/jobs/${encodeURIComponent(jobId)}/candidates/manual`, { method: "POST", body: JSON.stringify({ track_id: trackId, target, time_ms: timeMs, snap_to: snapTo }) }),

  uploadCollectionXml: (filename: string, xmlText: string) => req<CollectionXml>("/write/source-xml", { method: "POST", body: JSON.stringify({ filename, xml_text: xmlText }) }),
  getCollectionXml: (sourceId: string) => req<CollectionXml>(`/write/source-xml/${encodeURIComponent(sourceId)}`),

  buildPlan: (jobId: string, memoryCandidateIds?: string[], options?: { mode: ExportMode; source_id?: string; cue_colors?: { MEMORY: string | null; HOT: string }; track_ids?: string[] }) =>
    req<WritePlan>("/write/plan", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, memory_candidate_ids: memoryCandidateIds, ...options }),
    }),

  executePlan: (planId: string, confirmationHash: string) =>
    req<ExecuteResult>("/write/execute", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId, confirmation_hash: confirmationHash }),
    }),

  exportXml: (jobId: string, cueColors: { MEMORY: string | null; HOT: string }, memoryCandidateIds?: string[], options?: { mode: ExportMode; source_id?: string; confirmation_hash?: string; track_ids?: string[] }) =>
    req<ExportXmlResult>("/write/export-xml", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, cue_colors: cueColors, memory_candidate_ids: memoryCandidateIds, ...options }),
    }),

  downloadReport: async (jobId: string, trackIds?: string[]) => {
    const query = new URLSearchParams();
    trackIds?.forEach((id) => query.append("track_ids", id));
    const res = await fetch(`${BASE}/jobs/${jobId}/export.csv?${query}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`CSV を取得できませんでした (${res.status})`);
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `cue-report-${jobId.slice(0, 8)}.csv`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

// 進捗 WebSocket。トークンはクエリで渡す（WS はヘッダ制約があるため）。
export function openProgressSocket(jobId: string, afterSeq = 0): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/ws/jobs/${jobId}?token=${encodeURIComponent(
    token,
  )}&after_seq=${afterSeq}`;
  return new WebSocket(url);
}
