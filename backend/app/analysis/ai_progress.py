"""Read actual separator progress without estimating progress from track counts."""
from __future__ import annotations

from pathlib import Path
import re


def _seconds(value: str) -> int:
    result = 0
    for part in value.split(":"):
        result = result * 60 + int(part)
    return result


def inference_progress(log: Path, *, elapsed_sec: float = 0) -> dict:
    result = {"phase": "PREPARING", "percent": None, "elapsed_sec": max(0, round(elapsed_sec)), "remaining_sec": None}
    try:
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 16384))
            tail = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return result
    # tqdm writes carriage-return updates as well as newline updates. Ignore
    # unrelated output, partial lines, and unknown remaining times.
    matches = list(re.finditer(r"(?:^|[\r\n])\s*(\d{1,3})%\|[^\r\n]*?\[([\d:]+)<([\d:]+|\?)[,\]]", tail))
    if matches:
        match = matches[-1]
        percent = int(match[1])
        if 0 <= percent <= 100:
            result.update(phase="SEPARATING" if percent < 100 else "FINALIZING", percent=percent,
                          elapsed_sec=max(result["elapsed_sec"], _seconds(match[2])),
                          remaining_sec=None if match[3] == "?" else _seconds(match[3]))
    return result
