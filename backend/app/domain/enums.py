from __future__ import annotations

from enum import Enum


class CueType(str, Enum):
    INTRO_END = "INTRO_END"
    BREAK = "BREAK"
    BUILD = "BUILD"
    DROP = "DROP"
    OUTRO = "OUTRO"


class CueKind(str, Enum):
    MEMORY = "MEMORY"
    HOT = "HOT"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class BeatSource(str, Enum):
    ANLZ = "ANLZ"
    LIBROSA = "LIBROSA"


class WriteAction(str, Enum):
    ADD = "ADD"
    KEEP = "KEEP"
    REPLACE = "REPLACE"
    SKIP = "SKIP"
    CONFLICT = "CONFLICT"


class ErrorCode(str, Enum):
    RBX_RUNNING = "RBX_RUNNING"
    UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"
    DB_KEY_UNAVAILABLE = "DB_KEY_UNAVAILABLE"
    AUDIO_NOT_FOUND = "AUDIO_NOT_FOUND"
    AUDIO_NO_PERMISSION = "AUDIO_NO_PERMISSION"
    DECODE_FAILED = "DECODE_FAILED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    DB_LOCKED = "DB_LOCKED"
    DISK_FULL = "DISK_FULL"
    COMMIT_FAILED = "COMMIT_FAILED"
    VERIFY_MISMATCH = "VERIFY_MISMATCH"
    WRITE_DISABLED = "WRITE_DISABLED"
    PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
