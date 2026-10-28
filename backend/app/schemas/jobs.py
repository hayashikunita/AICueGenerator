from __future__ import annotations

from typing import Any, Literal

from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from ..domain.enums import CueType
from ..domain.cue_targets import INTRO_OUTRO_DEFAULT_TARGETS


class TrackInput(BaseModel):
    content_id: str
    path: str
    format: str = "WAV"
    duration_ms: int | None = None
    sample_rate: int | None = None
    rb_uuid: str | None = None
    writable: bool = False


class CuePreset(BaseModel):
    cue_kind: Literal["MEMORY", "HOT", "BOTH"] = "MEMORY"
    memory_color: str | None = Field(default="#00ffff", pattern=r"^#[0-9a-fA-F]{6}$")
    hot_color: str = Field(default="#ff5d73", pattern=r"^#[0-9a-fA-F]{6}$")


class IntroOutroSettings(BaseModel):
    targets: list[Literal["INTRO_START", "INTRO_BAR", "INTRO_BAR_X2", "INTRO_BAR_X3", "INTRO_INTERVAL", "INTRO_END_BEFORE", "INTRO_END", "OUTRO", "OUTRO_INTERVAL", "OUTRO_END_BEFORE", "OUTRO_END", "FADE_END_BEFORE", "FADE_END", "TRACK_END_BEFORE", "TRACK_END", "VOCAL_START", "VOCAL_END"]] = Field(default_factory=lambda: list(INTRO_OUTRO_DEFAULT_TARGETS), min_length=1, max_length=17)
    intro_position_bars: int = Field(default=8, ge=1, le=128)
    intro_interval_bars: int = Field(default=8, ge=1, le=128)
    intro_before_bars: int = Field(default=8, ge=1, le=128)
    outro_interval_bars: int = Field(default=8, ge=1, le=128)
    outro_before_bars: int = Field(default=8, ge=1, le=128)
    fade_before_bars: int = Field(default=8, ge=1, le=128)
    track_before_bars: int = Field(default=8, ge=1, le=128)


class JobParams(BaseModel):
    cue_mode: Literal["LEGACY", "PURPOSE", "INTRO_OUTRO"] = "LEGACY"
    legacy_vocal_start: bool = False
    legacy_vocal_end: bool = False
    intro_outro: IntroOutroSettings | None = None
    analysis_source: Literal["REKORDBOX", "AUDIO"] = "AUDIO"
    analysis_quality: Literal["STANDARD", "AI"] = "STANDARD"
    ai_scope: Literal["FULL", "VOCAL"] = "FULL"
    bpm: float | None = Field(default=None, gt=0, description="既知BPM。未指定なら推定")
    bars_per_phrase: int = Field(default=16, ge=1, le=128)
    beats_per_phrase: int | None = Field(default=None, ge=4, le=512, multiple_of=4, description="4/4拍子の解析単位。指定時は小節数より優先")
    top_k: int = Field(default=3, ge=1, le=20)
    cue_targets: list[Literal["INTRO_START", "INTRO_END", "OUTRO", "OUTRO_END", "CHORUS_START", "CHORUS_END", "CHORUS_END_MINUS_8_BARS", "VOCAL_START", "VOCAL_END"]] | None = Field(default=None, min_length=1, max_length=9)
    cue_default: CuePreset | None = None
    cue_settings: dict[CueType, CuePreset] = Field(default_factory=dict)
    end_alignment_bars: Literal[1, 4, 8, 16] = 1

    @model_validator(mode="after")
    def specialized_mode(self):
        if self.cue_mode == "INTRO_OUTRO":
            if self.intro_outro is None:
                self.intro_outro = IntroOutroSettings()
            if not {"VOCAL_START", "VOCAL_END"}.intersection(self.intro_outro.targets):
                self.analysis_quality = "STANDARD"  # Separation is only useful when requested.
            self.cue_targets = None
        if self.cue_mode != "LEGACY" or self.cue_targets is not None:
            self.legacy_vocal_start = False
            self.legacy_vocal_end = False
        targets = self.intro_outro.targets if self.cue_mode == "INTRO_OUTRO" else self.cue_targets or ([target for target, enabled in (("VOCAL_START", self.legacy_vocal_start), ("VOCAL_END", self.legacy_vocal_end)) if enabled])
        if self.ai_scope == "VOCAL" and not {"VOCAL_START", "VOCAL_END"}.intersection(targets):
            self.analysis_quality = "STANDARD"
        return self


class CreateJobRequest(BaseModel):
    params: JobParams = Field(default_factory=JobParams)
    tracks: list[TrackInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_tracks(self):
        ids = [t.content_id for t in self.tracks]
        paths = [str(Path(t.path).resolve()).casefold() for t in self.tracks]
        if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
            raise ValueError("同じ曲を重複して指定できません。")
        return self


class CreateJobResponse(BaseModel):
    job_id: str


class PreviewTrackOut(BaseModel):
    content_id: str
    state: Literal["CACHED", "NEW", "UNAVAILABLE"]
    reason: str | None = None


class PreviewJobResponse(BaseModel):
    total: int
    cached: int
    new: int
    unavailable: int
    tracks: list[PreviewTrackOut]


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
    can_resume: bool = False
    total: int
    completed: int
    failed: int
    created_at: str
    updated_at: str
    track_path: str | None = None
    track_title: str | None = None
    track_artist: str | None = None
    params: JobParams = Field(default_factory=JobParams)


class JobListResponse(BaseModel):
    jobs: list[JobSummary]


class JobTrackOut(BaseModel):
    id: str
    content_id: str
    path: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
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
    track_id: str | None = None
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


class BatchDecisionRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=1000)
    cue_kind: Literal["MEMORY", "HOT", "BOTH", "PRESET"]


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
    target: CueType


class PlanItemOut(BaseModel):
    color: str | None = None
    end_time_ms: int | None = None
    preset: CuePreset | None = None
    track_id: str
    cue_kind: str
    action: str
    time_ms: int
    slot: str | None = None
    reason: str = ""


class CueExportColors(BaseModel):
    MEMORY: str | None = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    HOT: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class CollectionXmlRequest(BaseModel):
    filename: str = Field(max_length=255)
    xml_text: str = Field(max_length=20 * 1024 * 1024)


class CollectionXmlResponse(BaseModel):
    source_id: str
    filename: str
    tracks: int


class BuildPlanRequest(BaseModel):
    job_id: str
    track_ids: list[str] | None = Field(default=None, min_length=1, max_length=200)
    memory_candidate_ids: list[str] | None = Field(default=None, max_length=2000)
    mode: Literal["COPY", "EXISTING"] = "COPY"
    source_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    cue_colors: CueExportColors | None = None


class WritePlanResponse(BaseModel):
    plan_id: str
    confirmation_hash: str
    add: int
    replace: int
    conflict: int
    items: list[PlanItemOut]
    mode: Literal["COPY", "EXISTING"] = "COPY"
    preserved: int = 0
    duplicates_skipped: int = 0
    source_name: str | None = None
    issues: list[str] = Field(default_factory=list)
    track_updates: list[dict[str, Any]] = Field(default_factory=list)


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
    track_ids: list[str] | None = Field(default=None, min_length=1, max_length=200)
    cue_colors: CueExportColors | None = None
    memory_candidate_ids: list[str] | None = Field(default=None, max_length=2000)
    mode: Literal["COPY", "EXISTING"] = "COPY"
    source_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    confirmation_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ExportXmlResponse(BaseModel):
    folder: str
    xml_path: str
    tracks: int
    cues: int
    copied: int
    skipped: list[str] = []
    cue_colors: dict[str, str | None] = Field(default_factory=dict)
    cue_settings_used: bool = False
    warnings: list[str] = Field(default_factory=list)
    mode: Literal["COPY", "EXISTING"] = "COPY"
    added_cues: int = 0
    preserved_cues: int = 0
    duplicates_skipped: int = 0
    backup_xml_path: str | None = None
