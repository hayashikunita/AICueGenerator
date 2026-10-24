// バックエンド API と一致する型定義。

export type Band = "high" | "review" | "reject";
export type CueKind = "MEMORY" | "HOT" | "BOTH";
export type CueTarget = "INTRO_START" | "OUTRO" | "CHORUS_START" | "CHORUS_END" | "CHORUS_END_MINUS_8_BARS" | "VOCAL_START";
export interface CuePosition { time_ms: number; beat: number | null }

export interface Diagnostics {
  process_running: boolean;
  db_key_available: boolean;
  schema_supported: boolean;
  cloud_sync_enabled: boolean | null;
  writable: boolean;
  state: string;
}

export interface JobParams {
  analysis_source?: "REKORDBOX" | "AUDIO";
  bpm?: number | null;
  bars_per_phrase?: number;
  beats_per_phrase?: number | null;
  top_k?: number;
  cue_targets?: CueTarget[] | null;
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

export interface RekordboxPlaylist {
  id: string;
  name: string;
  parent_id: string | null;
  path: string;
  is_folder: boolean;
  is_smart: boolean;
}

export interface RekordboxPlaylistListResult {
  available: boolean;
  reason: string | null;
  playlists: RekordboxPlaylist[];
}

export interface RekordboxPlaylistTracksResult extends RekordboxSearchResult {
  playlist_id: string;
  playlist_name: string | null;
  total: number;
  has_more: boolean;
}

export interface JobSummary {
  id: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  created_at: string;
  updated_at: string;
  track_path: string | null;
  params?: JobParams;
}

export interface JobTrack {
  id: string;
  content_id: string;
  path: string;
  format: string;
  duration_ms: number | null;
  status: string;
  analysis?: AnalysisInfo | null;
}

export interface AnalysisInfo {
  source: "REKORDBOX" | "AUDIO";
  available: boolean;
  reason?: string | null;
  bpm?: number | null;
  key?: string | null;
  beat_count?: number;
  downbeat_count?: number;
  phrase_count?: number;
  phrase_used?: boolean;
  section_labels_used?: boolean;
  existing_cues?: { time_ms: number; kind: number; comment: string }[];
  warnings?: string[];
}

export interface GridPreview {
  content_id: string;
  title: string;
  path: string;
  first_beat: number;
  beat_count: number;
  beats: { time_ms: number; before: number; after: number }[];
  blocked_reason: string | null;
}

export interface GridPlan extends GridPreview {
  plan_id: string;
  expires_in: number;
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
  original_time_ms?: number | null;
  edited_time_ms?: number | null;
  beat: number | null;
  confidence: number;
  rank: number;
  band: Band;
  evidence: Evidence[];
  accepted: boolean | null;
  cue_kind: CueKind | null;
}

export interface DecisionRequest {
  accepted: boolean;
  cue_kind: CueKind;
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
  cue_colors?: Partial<Record<"MEMORY" | "HOT", string>>;
  warnings?: string[];
}

export interface ProgressEvent {
  seq: number;
  type: string;
  job_id: string;
  ts: string;
  data: Record<string, unknown>;
}
