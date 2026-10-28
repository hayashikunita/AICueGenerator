"""Restore missing ordinal cues from saved grids without decoding or running AI."""
from __future__ import annotations

from ..common import dumps, loads, new_id, utcnow_iso
from ..domain.cue_targets import cue_target_label
from ..domain.enums import BeatSource, CueType
from ..domain.models import BeatGrid, CueCandidate
from ..persistence.repositories import Repository
from .intro_outro import INTRO_ORDINAL_MULTIPLIERS, intro_ordinal_candidates


def repair_intro_ordinals(repo: Repository, job_id: str) -> dict[str, int]:
    job = repo.get_job(job_id)
    if job is None:
        raise ValueError("解析履歴が見つかりません。")
    params = loads(job["params_json"]) or {}
    config = params.get("intro_outro") or {}
    summary = {"tracks": 0, "added": 0, "missing_origin": 0}
    if params.get("cue_mode") != "INTRO_OUTRO" or not set(config.get("targets", [])).intersection(INTRO_ORDINAL_MULTIPLIERS):
        return summary
    for track in repo.list_job_tracks(job_id):
        if track["status"] != "COMPLETED" or not track["run_id"]:
            continue
        run_id = str(track["run_id"])
        saved = repo.list_candidates_for_run(run_id)
        existing = {row["type"] for row in saved}
        if set(config["targets"]).intersection(INTRO_ORDINAL_MULTIPLIERS).issubset(existing):
            continue
        feature = repo.get_feature_summary(run_id)
        if feature is None:
            continue
        grid = BeatGrid(feature["bpm"] or 0, tuple(loads(feature["beat_times_json"])),
                        tuple(loads(feature["downbeats_json"])), BeatSource.ANLZ)
        start = next((row for row in saved if row["type"] == "INTRO_START"), None)
        if start is None:
            summary["missing_origin"] += 1
            continue
        origin = CueCandidate(CueType.INTRO_START, start["time_ms"] / 1000, start["beat"], start["confidence"], 1)
        analysis = loads(track["analysis_json"]) or {}
        duration = analysis.get("duration_ms", 0) / 1000
        # Header inspection keeps the sub-millisecond file boundary exact.
        reference = repo.get_track(track["track_id"])
        if reference is not None:
            try:
                import soundfile as sf
                duration = sf.info(reference["path"]).duration
            except (ImportError, OSError, RuntimeError):
                pass
        missing = [candidate for candidate in intro_ordinal_candidates(grid, origin, config, duration)
                   if candidate.cue_type.value not in existing]
        if not missing:
            continue
        with repo._conn:
            repo._conn.execute("BEGIN IMMEDIATE")
            current = repo._conn.execute("SELECT run_id,status FROM job_track WHERE job_id=? AND track_id=?",
                                         (job_id, track["track_id"])).fetchone()
            if current["run_id"] != run_id or current["status"] != "COMPLETED":
                continue
            existing = {row["type"] for row in repo.list_candidates_for_run(run_id)}
            missing = [candidate for candidate in missing if candidate.cue_type.value not in existing]
            if not missing:
                continue
            source = repo._conn.execute("SELECT * FROM analysis_run WHERE id=?", (run_id,)).fetchone()
            # Copy decisions and features; other jobs keep their original results.
            revision = {**(loads(source["params_json"]) or {}), "result_revision": new_id()}
            revised_run = repo._copy_completed_run(source, revision)
            repo._insert_candidates(revised_run, [{
                "type": candidate.cue_type.value, "time_ms": round(candidate.time_sec * 1000),
                "beat": candidate.beat_index, "confidence": candidate.confidence, "rank": candidate.rank,
                "evidence": [{"name": evidence.name, "weight": evidence.weight,
                              "score": evidence.score, "detail": evidence.detail} for evidence in candidate.evidence],
            } for candidate in missing])
            prefixes = tuple(cue_target_label(candidate.cue_type.value, params) + "：" for candidate in missing)
            analysis["warnings"] = [warning for warning in analysis.get("warnings", []) if not warning.startswith(prefixes)]
            analysis["intro_ordinals_repaired_at"] = utcnow_iso()
            repo._conn.execute("UPDATE job_track SET run_id=?,analysis_json=? WHERE job_id=? AND track_id=?",
                               (revised_run, dumps(analysis), job_id, track["track_id"]))
            repo._conn.execute("UPDATE analysis_job SET updated_at=? WHERE id=?", (utcnow_iso(), job_id))
        repo.add_audit(actor="system", action="repair_intro_ordinals", result="ok", job_id=job_id,
                       track_id=track["track_id"], after={"added": len(missing), "run_id": revised_run})
        summary["tracks"] += 1
        summary["added"] += len(missing)
    return summary
