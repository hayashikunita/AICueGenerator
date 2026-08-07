// バックエンド API と一致する型定義。

export type Band = "high" | "review" | "reject";

export interface Diagnostics {
  process_running: boolean;
  db_key_available: boolean;
  schema_supported: boolean;
  cloud_sync_enabled: boolean | null;
  writable: boolean;
  state: string;
}

export interface JobParams {
  bpm?: number | null;
  bars_per_phrase?: number;
  top_k?: number;
}

export interface TrackInput {
  content_id: string;
  path: string;
  format?: string;
  duration_ms?: number | null;
  sample_rate?: number | null;
  rb_uuid?: string | null;
  writable?: boolean;
}

export interface RekordboxTrack {
  content_id: string;
  title: string | null;
  artist: string | null;
  path: string | null;
  bpm: number | null;
  length_sec: number | null;
}

export interface RekordboxSearchResult {
  available: boolean;
  reason: string | null;
  tracks: RekordboxTrack[];
}

export interface JobSummary {
  id: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  created_at: string;
  updated_at: string;
}

export interface JobTrack {
  id: string;
  content_id: string;
  path: string;
  format: string;
  duration_ms: number | null;
  status: string;
}

export interface Evidence {
  name: string;
  weight: number;
  score: number;
  detail: string;
}

export interface Candidate {
  id: string;
  run_id: string;
  type: string;
  time_ms: number;
  beat: number | null;
  confidence: number;
  rank: number;
  band: Band;
  evidence: Evidence[];
}

export interface DecisionRequest {
  accepted: boolean;
  cue_kind: "MEMORY" | "HOT";
  edited_time_ms?: number | null;
  slot?: string | null;
  color?: string | null;
  comment?: string | null;
}

export interface PlanItem {
  track_id: string;
  cue_kind: string;
  action: string;
  time_ms: number;
  slot: string | null;
  reason: string;
}

export interface WritePlan {
  plan_id: string;
  confirmation_hash: string;
  add: number;
  replace: number;
  conflict: number;
  items: PlanItem[];
}

export interface ExecuteResult {
  ok: boolean;
  error_code: string | null;
  message: string;
  written: number;
  details: Record<string, unknown>;
}

export interface ExportXmlResult {
  folder: string;
  xml_path: string;
  tracks: number;
  cues: number;
  copied: number;
  skipped: string[];
}

export interface ProgressEvent {
  seq: number;
  type: string;
  job_id: string;
  ts: string;
  data: Record<string, unknown>;
}
