from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import get_settings
from ..rekordbox.adapter import open_rekordbox
from ..rekordbox.errors import AdapterError
from ..rekordbox.reader import get_content_detail, search_contents
from ..schemas.jobs import RekordboxSearchResponse, RekordboxTrack
from .deps import require_token

router = APIRouter(prefix="/api/v1/rekordbox", tags=["rekordbox"], dependencies=[Depends(require_token)])


def _settings_kwargs() -> dict[str, str | None]:
    s = get_settings()
    return {"path": s.rekordbox_db_path, "key": s.rekordbox_key}


@router.get("/tracks", response_model=RekordboxSearchResponse)
def search_tracks(
    query: str = Query(default="", description="タイトル/アーティストの部分一致"),
    limit: int = Query(default=20, ge=1, le=100),
) -> RekordboxSearchResponse:
    """rekordbox ライブラリから曲を検索する（読取専用）。"""
    try:
        with open_rekordbox(**_settings_kwargs()) as db:
            rows = search_contents(db, query, limit=limit)
    except AdapterError as exc:
        return RekordboxSearchResponse(available=False, reason=exc.message, tracks=[])
    return RekordboxSearchResponse(
        available=True, tracks=[RekordboxTrack(**r) for r in rows]
    )


@router.get("/tracks/{content_id}", response_model=RekordboxTrack)
def get_track(content_id: str) -> RekordboxTrack:
    """content_id から曲情報（パス・BPM 等）を取得する（読取専用）。"""
    try:
        with open_rekordbox(**_settings_kwargs()) as db:
            detail = get_content_detail(db, content_id)
    except AdapterError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="content not found")
    return RekordboxTrack(**detail)
