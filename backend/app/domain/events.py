"""WebSocket 進捗イベント定義（基本設計書 §7 WS再接続, §8 ジョブ）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    JOB_CREATED = "JOB_CREATED"
    TRACK_STARTED = "TRACK_STARTED"
    TRACK_COMPLETED = "TRACK_COMPLETED"
    TRACK_FAILED = "TRACK_FAILED"
    JOB_PROGRESS = "JOB_PROGRESS"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_FAILED = "JOB_FAILED"


@dataclass(frozen=True)
class ProgressEvent:
    """連番付き進捗イベント。seq でクライアント再接続時の取りこぼしを防ぐ。"""

    seq: int
    type: EventType
    job_id: str
    ts: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        return d
