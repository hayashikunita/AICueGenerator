"""Small, cancellable bridge to a separate CPU inference environment."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from ..config import get_settings
from .fingerprint import audio_fingerprint
from .ai_progress import inference_progress

AI_REVISION = "htdemucs-envelopes-1"
_INFERENCE_LOCK = threading.Lock()  # Never load two separators on this PC at once.


class AnalysisCancelled(Exception):
    pass


def ai_paths() -> tuple[Path, Path]:
    settings = get_settings()
    executable = Path(settings.ai_python) if settings.ai_python else Path(__file__).resolve().parents[2] / ".venv-ai" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return executable, settings.data_dir / "ai-models"


def ai_status() -> dict:
    executable, models = ai_paths()
    try:
        prepared = json.loads((models / "ready.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prepared = {}
    available = executable.is_file() and prepared.get("prepared") is True and prepared.get("model") == "htdemucs"
    return {"available": available, "model": "htdemucs", "local_only": True,
            "reason": None if available else "AI解析環境・モデルが未準備です。通常解析はそのまま使えます。"}


def _cancelled(event) -> bool:
    return event is not None and event.is_set()


def validate_stems(data: dict) -> dict:
    import math
    if data.get("schema") != 1 or data.get("model") != "htdemucs":
        raise ValueError("AI解析結果の形式を確認できません。")
    hop, duration = data.get("hop_sec", 0), data.get("duration_sec", 0)
    if not isinstance(hop, (int, float)) or not math.isfinite(hop) or not .01 <= hop <= .5 or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("AI解析結果の時間情報が不正です。")
    arrays = [data.get("mix"), *(data.get("stems", {}).get(key) for key in ("vocals", "drums", "bass", "other"))]
    expected = math.ceil(duration / hop)
    if any(not isinstance(values, list) or len(values) != expected or any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values) for values in arrays):
        raise ValueError("AI解析結果の音量データが不正です。")
    return data


def analyze_stems(path: str, *, cancel_event=None, progress_callback=None) -> tuple[dict, bool]:
    if not ai_status()["available"]:
        raise ValueError("AI解析環境・モデルが未準備です。通常解析を選ぶか、AI環境を準備してください。")
    original_fingerprint = audio_fingerprint(path)
    key = hashlib.sha256((AI_REVISION + original_fingerprint).encode()).hexdigest()
    cache = get_settings().data_dir / "ai-cache"
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / f"{key}.json"

    def cached():
        try:
            return validate_stems(json.loads(output.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    queued_at = time.monotonic()
    notified_at = -1.0

    def notify(progress):
        if progress_callback is not None:
            progress_callback(progress)

    while not _INFERENCE_LOCK.acquire(timeout=.2):
        if _cancelled(cancel_event):
            raise AnalysisCancelled()
        now = time.monotonic()
        if now - notified_at >= 1:
            notify({"phase": "WAITING", "percent": None, "elapsed_sec": round(now - queued_at), "remaining_sec": None})
            notified_at = now
    try:
        if _cancelled(cancel_event):
            raise AnalysisCancelled()
        data = cached()
        if data is not None:
            notify({"phase": "CACHED", "percent": 100, "elapsed_sec": 0, "remaining_sec": 0})
            return data, True
        executable, models = ai_paths()
        worker = Path(__file__).with_name("stem_worker.py")
        log = cache / f"{key}.log"
        environment = {**os.environ, "TORCH_HOME": str(models), "OMP_NUM_THREADS": "4"}
        # shell=False keeps arbitrary audio filenames out of shell syntax.
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen([str(executable), "-u", str(worker), "--audio", path, "--output", str(output), "--model-dir", str(models)],
                                       stdout=stream, stderr=stream, env=environment,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            started = time.monotonic()
            notified_at = -1.0
            try:
                while process.poll() is None:
                    if _cancelled(cancel_event):
                        raise AnalysisCancelled()
                    if time.monotonic() - started > 3600:
                        raise ValueError("AI解析が制限時間を超えました。通常解析での確認もできます。")
                    now = time.monotonic()
                    if now - notified_at >= 1:
                        notify(inference_progress(log, elapsed_sec=now - started))
                        notified_at = now
                    if cancel_event is not None:
                        cancel_event.wait(.2)
                    else:
                        time.sleep(.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            if _cancelled(cancel_event):
                raise AnalysisCancelled()
            data = cached()
            if process.returncode != 0 or data is None:
                raise ValueError("AI音源分離を完了できませんでした。通常解析を選んで再実行するか、AI環境を確認してください。")
            if audio_fingerprint(path) != original_fingerprint:
                output.unlink(missing_ok=True)
                raise ValueError("AI処理中に音源が変更されました。最新の音源で解析し直してください。")
            notify({"phase": "FINALIZING", "percent": 100, "elapsed_sec": round(time.monotonic() - started), "remaining_sec": 0})
        return data, False
    finally:
        _INFERENCE_LOCK.release()
