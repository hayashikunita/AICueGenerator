"""ジョブ管理（登録・実行・キャンセル）。

ThreadPoolExecutor でワーカーを実行する。SQLite は WAL のため read 並行＋単一 writer で
ローカル用途に十分。キャンセルは曲境界で反映する（基本設計書 §8）。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..persistence.repositories import Repository
from .progress import ProgressHub
from .worker import run_job


class JobManager:
    def __init__(self, db_path: Path, *, max_workers: int = 2) -> None:
        self._db_path = db_path
        self._hub = ProgressHub()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="aicue-job")
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    @property
    def hub(self) -> ProgressHub:
        return self._hub

    def submit(self, *, params: dict[str, Any], tracks: list[dict[str, Any]]) -> str:
        """曲参照を登録しジョブを作成、非同期実行を開始する。"""
        repo = Repository(self._db_path)
        try:
            track_ids: list[str] = []
            for t in tracks:
                tid = repo.upsert_track(
                    content_id=t["content_id"],
                    path=t["path"],
                    fmt=t.get("format", "WAV"),
                    duration_ms=t.get("duration_ms"),
                    sample_rate=t.get("sample_rate"),
                    rb_uuid=t.get("rb_uuid"),
                    writable=t.get("writable", False),
                )
                track_ids.append(tid)
            job_id = repo.create_job(params=params, track_ids=track_ids)
            repo.add_audit(actor="user", action="create_job", result="ok", job_id=job_id,
                           after={"tracks": len(track_ids)})
        finally:
            repo.close()

        cancel = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = cancel
        self._executor.submit(run_job, self._db_path, self._hub, job_id, params, cancel)
        return job_id

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
