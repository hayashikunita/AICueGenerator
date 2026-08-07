"""解析ワーカー（基本設計書 §8, §9）。

1曲ずつデコード→解析→候補を永続化し、進捗を publish する。キャッシュ(analysis_run)が
あれば再解析をスキップ。曲単位の失敗は継続（DECODE_FAILED 等）。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..analysis.pipeline import analyze_file
from ..common import ENGINE_VERSION
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
            _process_track(repo, hub, job_id, track_id, params)

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
    top_k = int(params.get("top_k") or 3)

    if not Path(path).exists():
        _fail_track(repo, hub, job_id, track_id, ErrorCode.AUDIO_NOT_FOUND)
        return

    try:
        result = analyze_file(path, bpm=bpm, bars_per_phrase=bars_per_phrase, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 - 曲単位失敗は継続
        repo.add_audit(actor="worker", action="analyze", result="error",
                       job_id=job_id, track_id=track_id, after={"error": str(exc)})
        _fail_track(repo, hub, job_id, track_id, ErrorCode.DECODE_FAILED)
        return

    cached = repo.find_cached_run(
        track_id=track_id,
        engine_version=ENGINE_VERSION,
        fingerprint=result.fingerprint,
        params=params,
    )
    if cached is not None:
        run_id = str(cached["id"])
        repo.set_job_track_status(job_id, track_id, "COMPLETED")
        repo.bump_job_counts(job_id, completed=1)
        hub.publish(
            job_id,
            EventType.TRACK_COMPLETED,
            {
                "track_id": track_id,
                "run_id": run_id,
                "candidates": len(repo.list_candidates_for_run(run_id)),
                "cached": True,
            },
        )
        _emit_progress(repo, hub, job_id)
        return

    run_id = repo.create_run(
        track_id=track_id,
        engine_version=ENGINE_VERSION,
        params=params,
        fingerprint=result.fingerprint,
        beat_source=result.beatgrid.source.value,
        pssi_used=False,
    )
    repo.save_feature_summary(
        run_id,
        bpm=result.beatgrid.bpm,
        beat_times=list(result.beatgrid.beat_times),
        downbeats=list(result.beatgrid.downbeat_indices),
    )
    repo.add_candidates(run_id, [_cue_to_row(c) for c in result.candidates])
    repo.finish_run(run_id, status="COMPLETED")

    repo.set_job_track_status(job_id, track_id, "COMPLETED")
    repo.bump_job_counts(job_id, completed=1)
    hub.publish(
        job_id,
        EventType.TRACK_COMPLETED,
        {"track_id": track_id, "run_id": run_id, "candidates": len(result.candidates)},
    )
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
