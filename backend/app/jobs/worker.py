"""解析ワーカー（基本設計書 §8, §9）。

1曲ずつデコード→解析→候補を永続化し、進捗を publish する。キャッシュ(analysis_run)が
あれば再解析をスキップ。曲単位の失敗は継続（DECODE_FAILED 等）。
"""

from __future__ import annotations

import threading
import hashlib
from pathlib import Path
from typing import Any

from ..analysis.pipeline import analyze_file
from ..analysis.fingerprint import file_analysis_inputs
from ..analysis.ai import analyze_stems, load_cached_stems, AnalysisCancelled
from ..analysis.vocals import vocal_start_from_stems, vocal_end_from_stems
from ..common import ENGINE_VERSION, dumps, loads, utcnow_iso
from ..config import get_settings
from ..domain.enums import BeatSource
from ..domain.models import BeatGrid, PhraseSection
from ..rekordbox.adapter import open_rekordbox
from ..rekordbox.reader import load_track_analysis
from ..domain.enums import ErrorCode
from ..domain.events import EventType
from ..persistence.repositories import Repository
from .progress import ProgressHub


def _cue_to_row(c: Any) -> dict[str, Any]:
    return {
        "type": c.cue_type.value,
        "time_ms": int(round(c.time_sec * 1000)),
        "beat": c.beat_index,
        "bar": None,
        "confidence": c.confidence,
        "rank": c.rank,
        "evidence": [
            {"name": e.name, "weight": e.weight, "score": round(e.score, 4), "detail": e.detail}
            for e in c.evidence
        ],
    }


def run_job(
    db_path: Path,
    hub: ProgressHub,
    job_id: str,
    params: dict[str, Any],
    cancel_event: threading.Event,
) -> None:
    """ジョブ本体。例外は握って JOB_FAILED を publish する。"""
    repo = Repository(db_path)
    try:
        repo.set_job_status(job_id, "RUNNING")
        hub.publish(job_id, EventType.JOB_CREATED, {"total": _job_total(repo, job_id)})
        tracks = repo.list_job_tracks(job_id)

        for jt in tracks:
            if cancel_event.is_set():
                repo.set_job_status(job_id, "CANCELLED")
                hub.publish(job_id, EventType.JOB_CANCELLED, {})
                return
            track_id = str(jt["track_id"])
            _process_track(repo, hub, job_id, track_id, params, cancel_event=cancel_event)

        if cancel_event.is_set():
            repo.set_job_status(job_id, "CANCELLED")
            hub.publish(job_id, EventType.JOB_CANCELLED, {})
            return
        repo.set_job_status(job_id, "COMPLETED")
        job = repo.get_job(job_id)
        hub.publish(
            job_id,
            EventType.JOB_COMPLETED,
            {"completed": int(job["completed"]), "failed": int(job["failed"])},
        )
    except Exception as exc:  # noqa: BLE001 - ワーカー全体の防御
        repo.set_job_status(job_id, "FAILED")
        repo.add_audit(actor="worker", action="run_job", result="error", job_id=job_id,
                       after={"error": str(exc)})
        hub.publish(job_id, EventType.JOB_FAILED, {"error": str(exc)})
    finally:
        repo.close()


def _job_total(repo: Repository, job_id: str) -> int:
    job = repo.get_job(job_id)
    return int(job["total"]) if job else 0


def _process_track(
    repo: Repository,
    hub: ProgressHub,
    job_id: str,
    track_id: str,
    params: dict[str, Any],
    *, cancel_event=None,
) -> None:
    track = repo.get_track(track_id)
    if track is None:
        repo.set_job_track_status(job_id, track_id, "FAILED", ErrorCode.AUDIO_NOT_FOUND.value)
        repo.bump_job_counts(job_id, failed=1)
        hub.publish(job_id, EventType.TRACK_FAILED,
                    {"track_id": track_id, "error": ErrorCode.AUDIO_NOT_FOUND.value})
        return

    repo.set_job_track_status(job_id, track_id, "RUNNING")
    hub.publish(job_id, EventType.TRACK_STARTED, {"track_id": track_id})
    path = str(track["path"])
    bpm = params.get("bpm")
    bars_per_phrase = int(params.get("bars_per_phrase") or 16)
    beats_per_phrase = params.get("beats_per_phrase")
    top_k = int(params.get("top_k") or 3)
    source = params.get("analysis_source", "AUDIO")
    analysis: dict[str, Any] = {"source": source, "available": False, "warnings": []}
    repo.set_job_track_analysis(job_id, track_id, analysis)

    if not Path(path).exists():
        analysis["reason"] = "音源が見つかりません。rekordbox の登録パスとファイルを確認してください"
        repo.set_job_track_analysis(job_id, track_id, analysis)
        _fail_track(repo, hub, job_id, track_id, ErrorCode.AUDIO_NOT_FOUND)
        return

    try:
        grid = None
        phrase_boundaries: tuple[int, ...] = ()
        phrase_sections: tuple[PhraseSection, ...] = ()
        source_fingerprint = None
        if source == "REKORDBOX":
            settings = get_settings()
            with open_rekordbox(path=settings.rekordbox_db_path, key=settings.rekordbox_key) as db:
                snapshot = load_track_analysis(db, str(track["content_id"]), path)
            grid = BeatGrid(snapshot["bpm"], tuple(snapshot["beat_times"]), tuple(snapshot["downbeat_indices"]), BeatSource.ANLZ)
            phrase_boundaries = tuple(snapshot["phrase_boundaries"])
            phrase_sections = tuple(PhraseSection(**s) for s in snapshot.get("phrase_sections", []))
            source_fingerprint = hashlib.sha256(dumps(snapshot).encode("utf-8")).hexdigest()
            analysis = {k: v for k, v in snapshot.items() if k not in {"beat_times", "downbeat_indices", "phrase_boundaries", "phrase_sections"}}
            analysis["section_labels_used"] = bool(params.get("cue_targets") and any(s.kind != "UNKNOWN" for s in phrase_sections))
            analysis["phrase_used"] = bool(phrase_boundaries)
            repo.set_job_track_analysis(job_id, track_id, analysis)
        stems = None
        specialized = params.get("cue_mode") == "INTRO_OUTRO"
        voice_targets = (params.get("intro_outro") or {}).get("targets", []) if specialized else params.get("cue_targets") or [target for target, enabled in (("VOCAL_START", params.get("legacy_vocal_start")), ("VOCAL_END", params.get("legacy_vocal_end"))) if enabled]
        vocal_requested = bool({"VOCAL_START", "VOCAL_END"}.intersection(voice_targets))
        require_end = "VOCAL_END" in voice_targets
        analysis["vocal_end_requested"] = require_end
        needs_ai = params.get("analysis_quality") == "AI" and (not specialized or vocal_requested)
        vocal_only = params.get("ai_scope") == "VOCAL"
        if needs_ai:
            stems = load_cached_stems(path, vocal_only=vocal_only, require_end=require_end)
        # Existing runs use the same fingerprint, so they can also be reused
        # before any decoding, feature extraction, or AI inference starts.
        if not needs_ai or stems is not None:
            fingerprint, _, _ = file_analysis_inputs(
                path, vocal_requested="VOCAL_START" in voice_targets, stem_analysis=stems,
            )
            if source_fingerprint:
                fingerprint = "sha256:" + hashlib.sha256((fingerprint + source_fingerprint).encode("ascii")).hexdigest()
            cached = repo.find_cached_run(
                track_id=track_id, engine_version=ENGINE_VERSION, fingerprint=fingerprint, params=params,
            )
            if cached is not None:
                saved_analysis = loads(cached["analysis_json"]) or analysis
                _reuse_cached_run(repo, hub, job_id, track_id, cached, saved_analysis)
                return
        if needs_ai:
            analysis.update(available=False, analysis_quality="AI", ai_started_at=utcnow_iso(), stage="AI音源分離を準備しています…")
            repo.set_job_track_analysis(job_id, track_id, analysis)

            def progress_changed(progress):
                phase = progress["phase"]
                message = {"WAITING": "ほかの曲のAI音源分離が終わるのを待っています。", "PREPARING": "AIモデル・音源を読み込んでいます。", "SEPARATING": "AIで音源を分離しています。", "FINALIZING": "音源分離の結果を整理しています。", "CACHED": "保存済みの音源分離結果を利用します。"}[phase]
                analysis.update(ai_progress=progress, stage=message)
                repo.set_job_track_analysis(job_id, track_id, analysis)
                hub.publish(job_id, EventType.JOB_PROGRESS, {"track_id": track_id, "ai_progress": progress})

            analysis["ai_scope"] = "VOCAL" if vocal_only else "FULL"
            stems, cached_stems = analyze_stems(path, cancel_event=cancel_event, progress_callback=progress_changed, vocal_only=vocal_only, require_end=require_end)
            if source == "REKORDBOX":
                with open_rekordbox(path=settings.rekordbox_db_path, key=settings.rekordbox_key) as db:
                    latest_snapshot = load_track_analysis(db, str(track["content_id"]), path)
                if hashlib.sha256(dumps(latest_snapshot).encode("utf-8")).hexdigest() != source_fingerprint:
                    raise ValueError("AI処理中にrekordboxのグリッド・フレーズ・Cue情報が変わりました。解析情報を再取得して実行し直してください。")
            analysis.update(ai_model=stems["model"], ai_cached=cached_stems,
                            vocal_start_sec=vocal_start_from_stems(stems), vocal_end_sec=vocal_end_from_stems(stems) if require_end else None, stage="音色・和音・ボーカルとフレーズを照合しています…")
            if stems.get("scope") == "VOCAL":
                analysis.update(vocal_analyzed_sec=stems["analyzed_sec"], vocal_scan_complete=stems["scan_complete"])
            repo.set_job_track_analysis(job_id, track_id, analysis)
        result = analyze_file(path, bpm=bpm, bars_per_phrase=bars_per_phrase, beats_per_phrase=beats_per_phrase, top_k=top_k, beatgrid=grid, phrase_boundaries=phrase_boundaries,
                              phrase_sections=phrase_sections, cue_targets=params.get("cue_targets"), end_alignment_bars=params.get("end_alignment_bars", 1),
                              stem_analysis=stems, intro_outro=(params.get("intro_outro") or {}) if specialized else None,
                              legacy_vocal_start=bool(params.get("legacy_vocal_start") and params.get("cue_mode", "LEGACY") == "LEGACY" and not params.get("cue_targets")),
                              legacy_vocal_end=bool(params.get("legacy_vocal_end") and params.get("cue_mode", "LEGACY") == "LEGACY" and not params.get("cue_targets")))
        if specialized:
            analysis.update(cue_mode="INTRO_OUTRO", analysis_quality="AI" if stems is not None else "STANDARD", section_labels_used=any(s.kind in {"INTRO", "OUTRO"} for s in phrase_sections))
        analysis.pop("stage", None)
        fingerprint = result.fingerprint
        if source_fingerprint:
            fingerprint = "sha256:" + hashlib.sha256((fingerprint + source_fingerprint).encode("ascii")).hexdigest()
        analysis.update(available=True, bpm=result.beatgrid.bpm, beat_source=result.beatgrid.source.value,
                        beat_count=result.beatgrid.beat_count, downbeat_count=len(result.beatgrid.downbeat_indices), duration_ms=round(result.duration_sec * 1000))
        analysis["warnings"] = list(analysis.get("warnings", [])) + list(result.warnings)
    except AnalysisCancelled:
        analysis.update(available=False, stage="キャンセルしました")
        repo.set_job_track_analysis(job_id, track_id, analysis)
        repo.set_job_track_status(job_id, track_id, "CANCELLED")
        return
    except Exception as exc:  # noqa: BLE001 - 曲単位失敗は継続
        analysis.update(available=False, reason=str(exc))
        repo.set_job_track_analysis(job_id, track_id, analysis)
        repo.add_audit(actor="worker", action="analyze", result="error",
                       job_id=job_id, track_id=track_id, after={"error": str(exc)})
        _fail_track(repo, hub, job_id, track_id, ErrorCode.DECODE_FAILED)
        return

    cached = repo.find_cached_run(
        track_id=track_id,
        engine_version=ENGINE_VERSION,
        fingerprint=fingerprint,
        params=params,
    )
    if cached is not None:
        _reuse_cached_run(repo, hub, job_id, track_id, cached, analysis)
        return

    run_id = repo.create_run(
        track_id=track_id,
        engine_version=ENGINE_VERSION,
        params=params,
        fingerprint=fingerprint,
        beat_source=result.beatgrid.source.value,
        pssi_used=bool(phrase_boundaries),
    )
    repo.save_feature_summary(
        run_id,
        bpm=result.beatgrid.bpm,
        beat_times=list(result.beatgrid.beat_times),
        downbeats=list(result.beatgrid.downbeat_indices),
    )
    repo.add_candidates(run_id, [_cue_to_row(c) for c in result.candidates])
    repo.finish_run(run_id, status="COMPLETED")
    repo.set_job_track_analysis(job_id, track_id, analysis, run_id)

    repo.set_job_track_status(job_id, track_id, "COMPLETED")
    repo.bump_job_counts(job_id, completed=1)
    hub.publish(
        job_id,
        EventType.TRACK_COMPLETED,
        {"track_id": track_id, "run_id": run_id, "candidates": len(result.candidates)},
    )
    _emit_progress(repo, hub, job_id)


def _reuse_cached_run(repo, hub, job_id, track_id, cached, analysis) -> None:
    run_id = str(cached["id"])
    analysis = {**analysis, "available": True, "cached": True}
    for key in ("stage", "ai_started_at", "ai_progress"):
        analysis.pop(key, None)
    if analysis.get("ai_model"):
        analysis["ai_cached"] = True
    repo.set_job_track_analysis(job_id, track_id, analysis, run_id)
    repo.set_job_track_status(job_id, track_id, "COMPLETED")
    repo.bump_job_counts(job_id, completed=1)
    hub.publish(job_id, EventType.TRACK_COMPLETED, {
        "track_id": track_id, "run_id": run_id,
        "candidates": len(repo.list_candidates_for_run(run_id)), "cached": True,
    })
    _emit_progress(repo, hub, job_id)


def _fail_track(
    repo: Repository, hub: ProgressHub, job_id: str, track_id: str, code: ErrorCode
) -> None:
    repo.set_job_track_status(job_id, track_id, "FAILED", code.value)
    repo.bump_job_counts(job_id, failed=1)
    hub.publish(job_id, EventType.TRACK_FAILED, {"track_id": track_id, "error": code.value})
    _emit_progress(repo, hub, job_id)


def _emit_progress(repo: Repository, hub: ProgressHub, job_id: str) -> None:
    job = repo.get_job(job_id)
    if job is None:
        return
    hub.publish(
        job_id,
        EventType.JOB_PROGRESS,
        {
            "total": int(job["total"]),
            "completed": int(job["completed"]),
            "failed": int(job["failed"]),
        },
    )
