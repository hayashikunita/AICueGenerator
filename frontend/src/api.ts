import type {
  Candidate,
  Diagnostics,
  DecisionRequest,
  ExecuteResult,
  JobParams,
  JobSummary,
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
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  diagnostics: () => req<Diagnostics>("/diagnostics"),

  createJob: (params: JobParams, tracks: TrackInput[]) =>
    req<{ job_id: string }>("/jobs", {
      method: "POST",
      body: JSON.stringify({ params, tracks }),
    }),

  listJobs: () => req<{ jobs: JobSummary[] }>("/jobs"),

  getJob: (id: string) => req<JobSummary>(`/jobs/${id}`),

  cancelJob: (id: string) =>
    req<{ cancelled: boolean }>(`/jobs/${id}/cancel`, { method: "POST" }),

  candidates: (jobId: string) =>
    req<{ candidates: Candidate[] }>(`/jobs/${jobId}/candidates`),

  decide: (candidateId: string, body: DecisionRequest) =>
    req<{ decision_id: string; candidate_id: string }>(
      `/candidates/${candidateId}/decision`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  buildPlan: (jobId: string) =>
    req<WritePlan>("/write/plan", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }),

  executePlan: (planId: string, confirmationHash: string) =>
    req<ExecuteResult>("/write/execute", {
      method: "POST",
      body: JSON.stringify({ plan_id: planId, confirmation_hash: confirmationHash }),
    }),

  reportCsvUrl: (jobId: string) => `${BASE}/jobs/${jobId}/export.csv`,
};

// 進捗 WebSocket。トークンはクエリで渡す（WS はヘッダ制約があるため）。
export function openProgressSocket(jobId: string, afterSeq = 0): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/ws/jobs/${jobId}?token=${encodeURIComponent(
    token,
  )}&after_seq=${afterSeq}`;
  return new WebSocket(url);
}
