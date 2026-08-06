from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..analysis.scoring import confidence_band
from ..common import loads
from ..persistence.repositories import Repository
from ..schemas.jobs import (
    CandidateOut,
    DecisionRequest,
    DecisionResponse,
    EvidenceOut,
)
from .deps import get_repo, require_token

router = APIRouter(prefix="/api/v1", tags=["candidates"], dependencies=[Depends(require_token)])


@router.get("/candidates/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: str, repo: Repository = Depends(get_repo)) -> CandidateOut:
    row = repo.get_candidate(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    d = dict(row)
    return CandidateOut(
        id=d["id"],
        run_id=d["run_id"],
        type=d["type"],
        time_ms=d["time_ms"],
        beat=d["beat"],
        confidence=d["confidence"],
        rank=d["rank"],
        band=confidence_band(float(d["confidence"])),
        evidence=[EvidenceOut(**e) for e in (loads(d.get("evidence_json")) or [])],
    )


@router.post("/candidates/{candidate_id}/decision", response_model=DecisionResponse)
def decide(
    candidate_id: str,
    req: DecisionRequest,
    repo: Repository = Depends(get_repo),
) -> DecisionResponse:
    row = repo.get_candidate(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    decision_id = repo.upsert_decision(
        candidate_id=candidate_id,
        accepted=req.accepted,
        cue_kind=req.cue_kind,
        edited_time_ms=req.edited_time_ms,
        slot=req.slot,
        color=req.color,
        comment=req.comment,
    )
    repo.add_audit(actor="user", action="decide", result="ok", target=candidate_id,
                   after={"accepted": req.accepted, "cue_kind": req.cue_kind})
    return DecisionResponse(decision_id=decision_id, candidate_id=candidate_id)
