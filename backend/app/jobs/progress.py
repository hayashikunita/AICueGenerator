"""進捗イベントハブ（スレッド安全, ポーリング配信）。

ワーカースレッドが publish し、WS 側は events_since で差分取得する。連番(seq)により
再接続時の取りこぼしを防ぐ（基本設計書 §7）。
"""

from __future__ import annotations

import threading
from collections import defaultdict

from ..common import utcnow_iso
from ..domain.events import EventType, ProgressEvent


class ProgressHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[ProgressEvent]] = defaultdict(list)
        self._seq = 0

    def publish(self, job_id: str, type_: EventType, data: dict | None = None) -> ProgressEvent:
        with self._lock:
            self._seq += 1
            event = ProgressEvent(
                seq=self._seq,
                type=type_,
                job_id=job_id,
                ts=utcnow_iso(),
                data=data or {},
            )
            self._events[job_id].append(event)
            return event

    def events_since(self, job_id: str, after_seq: int) -> list[ProgressEvent]:
        with self._lock:
            return [e for e in self._events.get(job_id, ()) if e.seq > after_seq]

    def latest_seq(self, job_id: str) -> int:
        with self._lock:
            events = self._events.get(job_id)
            return events[-1].seq if events else 0
