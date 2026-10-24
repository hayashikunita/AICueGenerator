from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import get_settings
from ..rekordbox.adapter import open_rekordbox
from ..rekordbox.errors import AdapterError
from ..rekordbox import grid_edit
from ..rekordbox.reader import get_content_detail, list_playlists, load_track_analysis, playlist_tracks, search_contents
from ..schemas.jobs import (
    RekordboxPlaylistListResponse,
    RekordboxPlaylistTracksResponse,
    RekordboxSearchResponse,
    RekordboxTrack,
    RekordboxAnalysisOut,
)
from .deps import require_token

router = APIRouter(prefix="/api/v1/rekordbox", tags=["rekordbox"], dependencies=[Depends(require_token)])


class GridPlanRequest(BaseModel):
    path: str = Field(min_length=1)
    first_beat: int = Field(ge=2, le=4)


class GridApplyRequest(BaseModel):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def _grid_action(action):
    try:
        with open_rekordbox(**_settings_kwargs()) as db:
            return action(db)
    except grid_edit.GridEditError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AdapterError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="小節頭のデータを処理できませんでした。解析ファイルと保存先のアクセス権を確認してください。") from exc


@router.get("/tracks/{content_id}/grid")
def grid_preview(content_id: str, path: str = Query(min_length=1)):
    return _grid_action(lambda db: grid_edit.preview(grid_edit.snapshot(db, content_id, path)))


@router.post("/tracks/{content_id}/grid/plan")
def grid_plan(content_id: str, body: GridPlanRequest):
    return _grid_action(lambda db: grid_edit.make_plan(grid_edit.snapshot(db, content_id, body.path), body.first_beat))


@router.post("/tracks/{content_id}/grid/apply")
def grid_apply(content_id: str, body: GridApplyRequest):
    return _grid_action(lambda db: grid_edit.apply_plan(db, content_id, body.plan_id, get_settings().data_dir / "grid-backups"))


@router.get("/tracks/{content_id}/analysis", response_model=RekordboxAnalysisOut)
def track_analysis(content_id: str, path: str | None = Query(default=None)) -> RekordboxAnalysisOut:
    try:
        with open_rekordbox(**_settings_kwargs()) as db:
            return RekordboxAnalysisOut(**load_track_analysis(db, content_id, path))
    except (AdapterError, ValueError) as exc:
        return RekordboxAnalysisOut(available=False, reason=str(exc))
    except Exception:
        return RekordboxAnalysisOut(available=False, reason="解析情報を読み取れませんでした。rekordbox で解析・保存してから再取得してください。")


def _settings_kwargs() -> dict[str, str | None]:
    s = get_settings()
    return {"path": s.rekordbox_db_path, "key": s.rekordbox_key}


@router.get("/playlists", response_model=RekordboxPlaylistListResponse)
def get_playlists() -> RekordboxPlaylistListResponse:
    try:
        with open_rekordbox(**_settings_kwargs()) as db:
            rows = list_playlists(db)
    except AdapterError as exc:
        return RekordboxPlaylistListResponse(available=False, reason=exc.message)
    except Exception:
        return RekordboxPlaylistListResponse(available=False, reason="プレイリストを読み取れませんでした。ライブラリの接続状態と形式を確認してください。")
    return RekordboxPlaylistListResponse(available=True, playlists=rows)


@router.get("/playlists/{playlist_id}/tracks", response_model=RekordboxPlaylistTracksResponse)
def get_playlist_tracks(
    playlist_id: str,
    query: str = Query(default=""),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> RekordboxPlaylistTracksResponse:
    try:
        with open_rekordbox(**_settings_kwargs()) as db:
            result = playlist_tracks(db, playlist_id)
    except AdapterError as exc:
        return RekordboxPlaylistTracksResponse(available=False, reason=exc.message, playlist_id=playlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        return RekordboxPlaylistTracksResponse(available=False, reason="プレイリストの曲を読み取れませんでした。ライブラリの接続状態と形式を確認してください。", playlist_id=playlist_id)
    if result is None:
        raise HTTPException(status_code=404, detail="playlist not found")
    name, tracks = result
    tokens = query.casefold().split()
    if tokens:
        tracks = [t for t in tracks if all(token in " ".join(str(t.get(k) or "") for k in ("title", "artist", "path")).casefold() for token in tokens)]
    return RekordboxPlaylistTracksResponse(
        available=True, playlist_id=playlist_id, playlist_name=name,
        tracks=tracks[offset:offset + limit], total=len(tracks), has_more=offset + limit < len(tracks),
    )


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
