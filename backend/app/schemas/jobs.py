from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TrackInput(BaseModel):
    content_id: str
    path: str
    format: str = "WAV"
    duration_ms: int | None = None
    sample_rate: int | None = None
    rb_uuid: str | None = None
    writable: bool = False


class JobParams(BaseModel):
    bpm: float | None = Field(default=None, gt=0, description="既知BPM。未指定なら推定")
    bars_per_phrase: int = 16
    top_k: int = 3


class CreateJobRequest(BaseModel):
    params: JobParams = Field(default_factory=JobParams)
    tracks: list[TrackInput] = Field(min_length=1)


class CreateJobResponse(BaseModel):
    job_id: str


class RekordboxTrack(BaseModel):
    content_id: str
    title: str | None = None
    artist: str | None = None
    path: str | None = None
    bpm: float | None = None
    length_sec: int | None = None


class RekordboxSearchResponse(BaseModel):
    available: bool
    reason: str | None = None
    tracks: list[RekordboxTrack] = []


class JobSummary(BaseModel):
    id: str
    status: str
    total: int
    completed: int
    failed: int
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    jobs: list[JobSummary]


class JobTrackOut(BaseModel):
    id: str
    content_id: str
    path: str
    format: str
    duration_ms: int | None = None
    status: str


class JobTrackListResponse(BaseModel):
    tracks: list[JobTrackOut]


class EvidenceOut(BaseModel):
    name: str
    weight: float
    score: float
    detail: str = ""


class CandidateOut(BaseModel):
    id: str
    run_id: str
    type: str
    time_ms: int
    beat: int | None
    confidence: int
    rank: int
    band: Literal["high", "review", "reject"]
    evidence: list[EvidenceOut]


class CandidateListResponse(BaseModel):
    candidates: list[CandidateOut]


class DecisionRequest(BaseModel):
    accepted: bool = True
    cue_kind: Literal["MEMORY", "HOT"] = "MEMORY"
    edited_time_ms: int | None = None
    slot: str | None = None
    color: str | None = None
    comment: str | None = None


class DecisionResponse(BaseModel):
    decision_id: str
    candidate_id: str


class PlanItemOut(BaseModel):
    track_id: str
    cue_kind: str
    action: str
    time_ms: int
    slot: str | None = None
    reason: str = ""


class BuildPlanRequest(BaseModel):
    job_id: str


class WritePlanResponse(BaseModel):
    plan_id: str
    confirmation_hash: str
    add: int
    replace: int
    conflict: int
    items: list[PlanItemOut]


class ExecutePlanRequest(BaseModel):
    plan_id: str
    confirmation_hash: str


class ExecutePlanResponse(BaseModel):
    ok: bool
    error_code: str | None = None
    message: str = ""
    written: int = 0
    details: dict[str, Any] = {}


class ExportXmlRequest(BaseModel):
    job_id: str


class ExportXmlResponse(BaseModel):
    folder: str
    xml_path: str
    tracks: int
    cues: int
    copied: int
    skipped: list[str] = []
