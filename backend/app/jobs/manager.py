"""ジョブ管理（登録・実行・キャンセル）。

ThreadPoolExecutor でワーカーを実行する。SQLite は WAL のため read 並行＋単一 writer で
ローカル用途に十分。キャンセルは曲境界で反映する（基本設計書 §8）。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..common import loads
from ..persistence.repositories import Repository
from ..rekordbox.metadata import read_track_metadata
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
            metadata = read_track_metadata(tracks)
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
                    metadata=metadata.get(str(t["content_id"])),
                )
                track_ids.append(tid)
            job_id = repo.create_job(params=params, track_ids=track_ids)
            repo.add_audit(actor="user", action="create_job", result="ok", job_id=job_id,
                           after={"tracks": len(track_ids)})
        finally:
            repo.close()

        with self._lock:
            self._start(job_id, params)
        return job_id

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel_events

    def resume(self, job_id: str) -> bool:
        """Resume an interrupted job, keeping its completed results and decisions."""
        with self._lock:
            if job_id in self._cancel_events:
                return False
            with Repository(self._db_path) as repo:
                job = repo.get_job(job_id)
                if job is None:
                    raise KeyError(job_id)
                if job["status"] not in {"PENDING", "RUNNING"}:
                    raise ValueError("この解析はすでに終了しています。")
                params = loads(job["params_json"])
            self._start(job_id, params)
        return True

    def _start(self, job_id: str, params: dict[str, Any]) -> None:
        # Called under _lock so simultaneous resume requests cannot start twice.
        cancel = threading.Event()
        self._cancel_events[job_id] = cancel
        try:
            self._executor.submit(self._run, job_id, params, cancel)
        except Exception:
            self._cancel_events.pop(job_id, None)
            raise

    def _run(self, job_id: str, params: dict[str, Any], cancel: threading.Event) -> None:
        try:
            run_job(self._db_path, self._hub, job_id, params, cancel)
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def shutdown(self) -> None:
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
