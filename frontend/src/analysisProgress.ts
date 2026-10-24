import type { AnalysisInfo } from "./types";

// Coverage is confirmed at a window boundary. A new window's 0% must never
// reset the song-wide coverage, and unknown preparation progress stays unknown.
export function vocalCoverage(data: AnalysisInfo | null | undefined, durationMs?: number | null) {
  const progress = data?.ai_progress;
  const total = progress?.audio_duration_sec ?? (data?.duration_ms ?? durationMs ?? 0) / 1000;
  if (!Number.isFinite(total) || total <= 0) return null;
  const checked = data?.vocal_analyzed_sec ?? (progress?.percent === 100 ? progress?.scan_end_sec : progress?.scan_start_sec);
  if (checked == null || !Number.isFinite(checked)) return null;
  const seconds = Math.max(0, Math.min(total, checked));
  return { seconds, total, percent: Math.floor(seconds / total * 100) };
}
