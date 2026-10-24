"""Keep rekordbox display metadata in the app without changing source tracks."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..common import loads
from ..config import get_settings
from .adapter import AdapterError, open_rekordbox
from .reader import get_content_detail


def track_metadata(row: Any) -> dict[str, Any]:
    metadata = loads(row["metadata_json"]) if row["metadata_json"] else {}
    return metadata if isinstance(metadata, dict) else {}


def read_track_metadata(tracks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tracks = [t for t in tracks if str(t["content_id"]).isdigit()]
    if not tracks:
        return {}
    settings = get_settings()
    result: dict[str, dict[str, Any]] = {}
    try:
        with open_rekordbox(path=settings.rekordbox_db_path, key=settings.rekordbox_key) as db:
            for track in tracks:
                content_id = str(track["content_id"])
                detail = get_content_detail(db, content_id)
                if not detail or not detail.get("path"):
                    continue
                # An ID alone must never attach another audio file's metadata.
                if Path(detail["path"]).resolve() != Path(track["path"]).resolve():
                    continue
                result[content_id] = {key: detail.get(key) for key in ("title", "artist", "album")}
    except AdapterError:
        logging.getLogger(__name__).warning("rekordboxの曲名を取得できないため、保存済みの情報またはファイル名を使用します。")
    return result


def backfill_track_metadata(repo: Any) -> None:
    """Upgrade existing app references only; library, files and cues stay intact."""
    tracks = [dict(row) for row in repo.list_tracks_missing_metadata()]
    metadata = read_track_metadata(tracks)
    for track in tracks:
        value = metadata.get(str(track["content_id"]))
        if value is not None:
            repo.set_track_metadata(track["id"], value)
