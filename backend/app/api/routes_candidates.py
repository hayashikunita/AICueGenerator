from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..common import loads
from ..persistence.repositories import Repository
from ..schemas.jobs import (
    CandidateOut,
    DecisionRequest,
    DecisionResponse,
    PositionRequest,
    ManualCandidateRequest,
    BatchDecisionRequest,
    CandidateListResponse,
)
from .deps import get_repo, require_token
from .candidate_presenter import candidate_out, nearest_index

router = APIRouter(prefix="/api/v1", tags=["candidates"], dependencies=[Depends(require_token)])


@router.post("/jobs/{job_id}/candidates/accept", response_model=CandidateListResponse)
def accept_candidates(job_id: str, req: BatchDecisionRequest, repo: Repository = Depends(get_repo)) -> CandidateListResponse:
    if repo.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        repo.accept_candidates(job_id, req.candidate_ids, req.cue_kind)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    repo.add_audit(actor="user", action="accept_candidates", result="ok", job_id=job_id,
                   after={"candidate_ids": req.candidate_ids, "cue_kind": req.cue_kind})
    return CandidateListResponse(candidates=[candidate_out(r) for r in repo.list_candidates_for_job(job_id)])


@router.get("/candidates/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: str, repo: Repository = Depends(get_repo)) -> CandidateOut:
    row = repo.get_candidate(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate_out(row)


def resolve_position(repo: Repository, run_id: str, req: PositionRequest) -> dict:
    summary = repo.get_feature_summary(run_id)
    times = loads(summary["beat_times_json"]) if summary else []
    indices = list(range(len(times))) if req.snap_to == "BEAT" else (loads(summary["downbeats_json"]) if summary else [])
    if not times or not indices:
        raise HTTPException(status_code=409, detail="この解析結果には拍位置がありません。曲を再解析してください。")
    if req.time_ms > round(times[-1] * 1000):
        raise HTTPException(status_code=400, detail="曲のグリッド範囲内の時刻を指定してください。")
    position = nearest_index([times[i] for i in indices], req.time_ms / 1000) + req.step
    if not 0 <= position < len(indices):
        raise HTTPException(status_code=400, detail="これ以上は曲の先頭・末尾を超えるため移動できません。")
    beat = indices[position]
    return {"time_ms": round(times[beat] * 1000), "beat": beat}


@router.post("/candidates/{candidate_id}/preview-position")
def preview_position(candidate_id: str, req: PositionRequest, repo: Repository = Depends(get_repo)) -> dict:
    row = repo.get_candidate(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return resolve_position(repo, row["run_id"], req)


@router.post("/jobs/{job_id}/candidates/manual", response_model=CandidateOut, status_code=201)
def add_manual_candidate(job_id: str, req: ManualCandidateRequest, repo: Repository = Depends(get_repo)) -> CandidateOut:
    if repo.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    row = next((r for r in repo.list_job_tracks(job_id) if r["track_id"] == req.track_id), None)
    if row is None or not row["run_id"]:
        raise HTTPException(status_code=409, detail="解析済みの対象曲を選んでください。")
    position = resolve_position(repo, row["run_id"], req)
    candidate = {**position, "type": req.target, "evidence": [{"name": "利用者が指定した位置", "weight": 100, "score": 0,
                 "detail": "試聴して指定した位置を解析済みグリッドへ合わせました。自動検出ではありません。"}]}
    try:
        candidate_id = repo.add_manual_candidate(job_id, req.track_id, candidate)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    repo.add_audit(actor="user", action="manual_candidate", result="ok", target=candidate_id, job_id=job_id, after=position)
    return candidate_out(repo.get_candidate(candidate_id))


@router.post("/candidates/{candidate_id}/decision", response_model=DecisionResponse)
def decide(
    candidate_id: str,
    req: DecisionRequest,
    repo: Repository = Depends(get_repo),
) -> DecisionResponse:
    row = repo.get_candidate(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    def value(field):
        return getattr(req, field) if field in req.model_fields_set else row[field]
    edited_time_ms = value("edited_time_ms")
    summary = repo.get_feature_summary(row["run_id"])
    times = loads(summary["beat_times_json"]) if summary else []
    if edited_time_ms is not None and times and edited_time_ms > round(times[-1] * 1000):
        raise HTTPException(status_code=400, detail="曲のグリッド範囲内の時刻を指定してください。")
    decision_id = repo.upsert_decision(
        candidate_id=candidate_id,
        accepted=req.accepted,
        cue_kind=req.cue_kind,
        edited_time_ms=edited_time_ms,
        slot=value("slot"),
        color=value("color"),
        comment=value("comment"),
    )
    repo.add_audit(actor="user", action="decide", result="ok", target=candidate_id,
                   after={"accepted": req.accepted, "cue_kind": req.cue_kind})
    updated = candidate_out(repo.get_candidate(candidate_id))
    return DecisionResponse(decision_id=decision_id, candidate_id=candidate_id, time_ms=updated.time_ms, beat=updated.beat)
