from __future__ import annotations

from pathlib import Path
from typing import Any


def _content_bpm(content: Any) -> float | None:
    # DjmdContent.BPM は BPM×100 の整数で保持される。
    raw = getattr(content, "BPM", None)
    if not raw:
        return None
    try:
        return round(float(raw) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def _content_artist(content: Any) -> str | None:
    artist = getattr(content, "Artist", None)
    if artist is not None:
        name = getattr(artist, "Name", None)
        if name:
            return str(name)
    name = getattr(content, "ArtistName", None)
    return str(name) if name else None


def content_to_dict(content: Any) -> dict[str, Any]:
    """DjmdContent を UI 向けの辞書へ変換する。"""
    return {
        "content_id": str(getattr(content, "ID", "") or ""),
        "title": (getattr(content, "Title", None) or None),
        "artist": _content_artist(content),
        "path": (getattr(content, "FolderPath", None) or None),
        "bpm": _content_bpm(content),
        "length_sec": getattr(content, "Length", None),
    }


def get_content_detail(db: Any, content_id: str) -> dict[str, Any] | None:
    """content_id から曲情報（パス・BPM 等）を1件取得する。"""
    try:
        content = db.get_content(ID=content_id)
    except Exception:  # noqa: BLE001 - 取得不能は None 扱い
        return None
    # pyrekordbox は ID 指定時に単一オブジェクト（または None）を返す。
    if content is not None and hasattr(content, "one_or_none"):
        content = content.one_or_none()
    if content is None:
        return None
    return content_to_dict(content)


def search_contents(db: Any, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """タイトル/アーティストの部分一致で曲を検索する（大文字小文字無視）。"""
    out: list[dict[str, Any]] = []
    try:
        rows = db.get_content()
    except Exception:  # noqa: BLE001
        return out
    needle = (query or "").strip().lower()
    for content in rows:
        title = str(getattr(content, "Title", "") or "")
        artist = _content_artist(content) or ""
        if needle and needle not in f"{title} {artist}".lower():
            continue
        out.append(content_to_dict(content))
        if len(out) >= limit:
            break
    return out


def list_playlists(db: Any) -> list[dict[str, Any]]:
    """プレイリスト一覧 (id, name)。API 差異に備え防御的に取得する。"""
    out: list[dict[str, Any]] = []
    try:
        rows = db.get_playlist()
    except Exception:  # noqa: BLE001
        return out
    for pl in rows:
        out.append(
            {
                "id": getattr(pl, "ID", None),
                "name": getattr(pl, "Name", None),
                "parent_id": getattr(pl, "ParentID", None),
            }
        )
    return out


def get_cues(db: Any, content_id: Any) -> list[dict[str, Any]]:
    """DB 側 (DjmdCue) のキュー一覧を返す。"""
    out: list[dict[str, Any]] = []
    try:
        rows = db.get_cue(ContentID=content_id)
    except Exception:  # noqa: BLE001
        return out
    for cue in rows:
        out.append(
            {
                "id": getattr(cue, "ID", None),
                "in_msec": getattr(cue, "InMsec", None),
                "kind": getattr(cue, "Kind", None),
                "comment": getattr(cue, "Comment", None),
                "usn": getattr(cue, "rb_local_usn", None),
            }
        )
    return out


def _anlz_paths(db: Any, content: Any) -> dict[str, str]:
    try:
        paths = db.get_anlz_paths(content)
    except Exception:  # noqa: BLE001
        return {}
    result: dict[str, str] = {}
    for key, value in dict(paths).items():
        if value:
            result[str(key)] = str(value)
    return result


def _parse_anlz(path: str) -> Any | None:
    try:
        from pyrekordbox import AnlzFile
    except Exception:  # noqa: BLE001
        return None
    try:
        return AnlzFile.parse_file(path)
    except Exception:  # noqa: BLE001
        return None


def read_beatgrid(db: Any, content: Any) -> dict[str, Any]:
    """ANLZ (PQTZ) からビートグリッド概要を読む。書込はしない。"""
    info: dict[str, Any] = {"available": False, "beat_count": 0, "downbeat_count": 0}
    paths = _anlz_paths(db, content)
    src = paths.get("DAT") or paths.get("EXT")
    if not src:
        return info
    anlz = _parse_anlz(src)
    if anlz is None:
        return info
    try:
        tag = anlz.get("PQTZ")
    except Exception:  # noqa: BLE001
        tag = None
    if tag is None:
        return info
    beats = getattr(getattr(tag, "content", tag), "entries", None)
    if beats is None:
        beats = getattr(tag, "beats", None)
    if beats is None:
        return info
    beats = list(beats)
    downbeats = sum(1 for b in beats if getattr(b, "beat_number", None) == 1)
    info.update(
        available=True,
        source=Path(src).suffix.lstrip("."),
        beat_count=len(beats),
        downbeat_count=downbeats,
    )
    return info


def read_phrases(db: Any, content: Any) -> dict[str, Any]:
    """ANLZ (PSSI) からフレーズ解析概要を読む。書込はしない。"""
    info: dict[str, Any] = {"available": False, "phrase_count": 0}
    paths = _anlz_paths(db, content)
    src = paths.get("EXT") or paths.get("EX2")
    if not src:
        return info
    anlz = _parse_anlz(src)
    if anlz is None:
        return info
    try:
        tag = anlz.get("PSSI")
    except Exception:  # noqa: BLE001
        tag = None
    if tag is None:
        return info
    content_obj = getattr(tag, "content", tag)
    entries = getattr(content_obj, "entries", None)
    info.update(
        available=True,
        mood=getattr(content_obj, "mood", None),
        phrase_count=len(list(entries)) if entries is not None else 0,
    )
    return info
