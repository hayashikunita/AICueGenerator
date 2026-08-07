from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..persistence.repositories import Repository
from .deps import get_repo, require_token_query

router = APIRouter(prefix="/api/v1", tags=["audio"])

_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}
_CHUNK = 64 * 1024


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/tracks/{track_id}/audio")
def stream_audio(
    track_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
    _: None = Depends(require_token_query),
) -> StreamingResponse:
    """DB に登録済みの曲だけを Range 対応でストリーム配信する（任意パスは配信しない）。"""
    row = repo.get_track(track_id)
    if row is None:
        raise HTTPException(status_code=404, detail="track not found")
    path = Path(str(row["path"]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="audio file not found")

    file_size = path.stat().st_size
    media_type = _media_type(path)
    range_header = request.headers.get("range")

    if range_header and range_header.strip().startswith("bytes="):
        spec = range_header.strip()[len("bytes=") :].split(",")[0].strip()
        start_s, _, end_s = spec.partition("-")
        if start_s == "":
            # 末尾からのサフィックス指定 (bytes=-500)
            suffix = int(end_s) if end_s else 0
            length = min(suffix, file_size)
            start = file_size - length
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
            end = min(end, file_size - 1)
        if start > end or start >= file_size:
            raise HTTPException(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
                detail="requested range not satisfiable",
            )
        length = end - start + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        }
        return StreamingResponse(
            _iter_file(path, start, length),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(file_size)}
    return StreamingResponse(
        _iter_file(path, 0, file_size), media_type=media_type, headers=headers
    )
