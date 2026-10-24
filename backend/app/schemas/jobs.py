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
    analysis_source: Literal["REKORDBOX", "AUDIO"] = "AUDIO"
    bpm: float | None = Field(default=None, gt=0, description="既知BPM。未指定なら推定")
    bars_per_phrase: int = Field(default=16, ge=1, le=128)
    beats_per_phrase: int | None = Field(default=None, ge=4, le=512, multiple_of=4, description="4/4拍子の解析単位。指定時は小節数より優先")
    top_k: int = Field(default=3, ge=1, le=20)
    cue_targets: list[Literal["INTRO_START", "OUTRO", "CHORUS_START", "CHORUS_END", "CHORUS_END_MINUS_8_BARS", "VOCAL_START"]] | None = Field(default=None, min_length=1, max_length=6)


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


class RekordboxPlaylist(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    path: str
    is_folder: bool = False
    is_smart: bool = False


class RekordboxPlaylistListResponse(BaseModel):
    available: bool
    reason: str | None = None
    playlists: list[RekordboxPlaylist] = Field(default_factory=list)


class RekordboxPlaylistTracksResponse(RekordboxSearchResponse):
    playlist_id: str
    playlist_name: str | None = None
    total: int = 0
    has_more: bool = False


class JobSummary(BaseModel):
    id: str
    status: str
    total: int
    completed: int
    failed: int
    created_at: str
    updated_at: str
    track_path: str | None = None
    params: JobParams = Field(default_factory=JobParams)


class JobListResponse(BaseModel):
    jobs: list[JobSummary]


class JobTrackOut(BaseModel):
    id: str
    content_id: str
    path: str
    format: str
    duration_ms: int | None = None
    status: str
    analysis: dict[str, Any] | None = None


class RekordboxAnalysisOut(BaseModel):
    available: bool
    source: str = "REKORDBOX"
    reason: str | None = None
    title: str | None = None
    bpm: float | None = None
    key: str | None = None
    beat_count: int = 0
    downbeat_count: int = 0
    phrase_count: int = 0
    existing_cues: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    original_time_ms: int | None = None
    edited_time_ms: int | None = None
    beat: int | None
    confidence: int
    rank: int
    band: Literal["high", "review", "reject"]
    evidence: list[EvidenceOut]
    accepted: bool | None = None
    cue_kind: Literal["MEMORY", "HOT", "BOTH"] | None = None


class CandidateListResponse(BaseModel):
    candidates: list[CandidateOut]


class DecisionRequest(BaseModel):
    accepted: bool = True
    cue_kind: Literal["MEMORY", "HOT", "BOTH"] = "MEMORY"
    edited_time_ms: int | None = Field(default=None, ge=0)
    slot: str | None = None
    color: str | None = None
    comment: str | None = None


class DecisionResponse(BaseModel):
    decision_id: str
    candidate_id: str
    time_ms: int | None = None
    beat: int | None = None


class PositionRequest(BaseModel):
    time_ms: int = Field(ge=0)
    snap_to: Literal["BEAT", "BAR"] = "BEAT"
    step: int = Field(default=0, ge=-128, le=128)


class ManualCandidateRequest(PositionRequest):
    track_id: str
    target: Literal["INTRO_START", "OUTRO", "CHORUS_START", "CHORUS_END", "CHORUS_END_MINUS_8_BARS", "VOCAL_START"]


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


class CueExportColors(BaseModel):
    MEMORY: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    HOT: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class ExportXmlRequest(BaseModel):
    job_id: str
    cue_colors: CueExportColors | None = None


class ExportXmlResponse(BaseModel):
    folder: str
    xml_path: str
    tracks: int
    cues: int
    copied: int
    skipped: list[str] = []
    cue_colors: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
