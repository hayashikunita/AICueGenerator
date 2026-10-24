from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..persistence.repositories import Repository
from ..config import get_settings
from ..rekordbox.adapter import open_rekordbox
from ..rekordbox.errors import AdapterError
from ..rekordbox.reader import get_content_detail
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
    return audio_response(Path(str(row["path"])), request)


@router.get("/rekordbox/tracks/{content_id}/audio")
def stream_library_audio(
    content_id: str,
    request: Request,
    path: str = Query(min_length=1),
    _: None = Depends(require_token_query),
) -> StreamingResponse:
    """Resolve the selected library track read-only, before any analysis job exists."""
    settings = get_settings()
    try:
        with open_rekordbox(path=settings.rekordbox_db_path, key=settings.rekordbox_key) as db:
            detail = get_content_detail(db, content_id)
    except AdapterError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    if detail is None or not detail.get("path"):
        raise HTTPException(status_code=404, detail="選択した曲の音源が見つかりません。")
    registered = Path(detail["path"])
    if registered.resolve() != Path(path).resolve():
        raise HTTPException(status_code=409, detail="選択中の曲と音源のパスが一致しません。曲を選び直してください。")
    return audio_response(registered, request)


def audio_response(path: Path, request: Request) -> StreamingResponse:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="音源ファイルが見つかりません。保存場所を確認してください。")

    file_size = path.stat().st_size
    media_type = _media_type(path)
    range_header = request.headers.get("range")

    if range_header and range_header.strip().startswith("bytes="):
        spec = range_header.strip()[len("bytes=") :].split(",")[0].strip()
        try:
            start_s, separator, end_s = spec.partition("-")
            if not separator or not (start_s or end_s) or any(s and (not s.isascii() or not s.isdigit()) for s in (start_s, end_s)):
                raise ValueError("invalid range")
            if start_s == "":
                suffix = int(end_s)
                start = file_size - min(suffix, file_size)
                end = file_size - 1
            else:
                start = int(start_s)
                end = min(int(end_s), file_size - 1) if end_s else file_size - 1
        except ValueError:
            raise HTTPException(status_code=416, headers={"Content-Range": f"bytes */{file_size}"}, detail="requested range not satisfiable") from None
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
