from __future__ import annotations

from pathlib import Path
import math
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
        "album": _content_album(content),
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


def _content_album(content: Any) -> str | None:
    album = getattr(content, "Album", None)
    if album is not None:
        name = getattr(album, "Name", None)
        if name:
            return str(name)
    name = getattr(content, "AlbumName", None)
    return str(name) if name else None


def search_contents(db: Any, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """曲を検索する。タイトル/アーティスト/アルバム/ファイルパスを対象に、
    空白区切りの全語が含まれる曲を返す（大文字小文字は無視）。"""
    out: list[dict[str, Any]] = []
    try:
        rows = db.get_content()
    except Exception:  # noqa: BLE001
        return out
    tokens = [t for t in (query or "").strip().lower().split() if t]
    for content in rows:
        title = str(getattr(content, "Title", "") or "")
        artist = _content_artist(content) or ""
        album = _content_album(content) or ""
        path = str(getattr(content, "FolderPath", "") or "")
        haystack = f"{title} {artist} {album} {path}".lower()
        if tokens and not all(tok in haystack for tok in tokens):
            continue
        out.append(content_to_dict(content))
        if len(out) >= limit:
            break
    return out


def list_playlists(db: Any) -> list[dict[str, Any]]:
    """フォルダ階層を含むプレイリスト一覧を取得する。取得失敗は呼び出し元へ返す。"""
    out: list[dict[str, Any]] = []
    for pl in db.get_playlist():
        out.append(
            {
                "id": str(pl.ID),
                "name": pl.Name or "(無題)",
                "parent_id": str(pl.ParentID) if pl.ParentID else None,
                "is_folder": bool(pl.is_folder),
                "is_smart": bool(pl.is_smart_playlist),
            }
        )
    by_id = {p["id"]: p for p in out}
    for playlist in out:
        names = [playlist["name"]]
        seen = {playlist["id"]}
        parent = playlist["parent_id"]
        while parent in by_id and parent not in seen:
            seen.add(parent)
            names.insert(0, by_id[parent]["name"])
            parent = by_id[parent]["parent_id"]
        playlist["path"] = " / ".join(names)
    return sorted(out, key=lambda p: (p["path"].casefold(), p["id"]))


def playlist_tracks(db: Any, playlist_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    """通常リストは TrackNo 順、スマートリストは条件に一致する曲を取得する。"""
    playlist = db.get_playlist(ID=playlist_id)
    if playlist is None:
        return None
    if playlist.is_folder:
        raise ValueError("フォルダ内のプレイリストを選んでください")
    if playlist.is_smart_playlist:
        contents = sorted(db.get_playlist_contents(playlist), key=lambda c: ((c.Title or "").casefold(), str(c.ID)))
    else:
        songs = sorted(db.get_playlist_songs(PlaylistID=playlist_id), key=lambda s: (s.TrackNo or 0, str(s.ID)))
        contents = [s.Content for s in songs if s.Content is not None]
    return playlist.Name or "(無題)", [content_to_dict(c) for c in contents]


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


def _analysis_tag(db: Any, content: Any, kind: str, order: tuple[str, ...]) -> tuple[Any, str] | None:
    paths = _anlz_paths(db, content)
    for extension in order:
        path = paths.get(extension)
        if not path:
            continue
        anlz = _parse_anlz(path)
        if anlz is None:
            continue
        try:
            return anlz.get_tag(kind), path
        except (IndexError, KeyError):
            continue
    return None


def read_beatgrid(db: Any, content: Any) -> dict[str, Any]:
    """ANLZ (PQTZ) からビートグリッド概要を読む。書込はしない。"""
    info: dict[str, Any] = {"available": False, "beat_count": 0, "downbeat_count": 0}
    found = _analysis_tag(db, content, "PQTZ", ("DAT", "EXT", "2EX"))
    if found is None:
        return info
    tag, src = found
    beats = getattr(getattr(tag, "content", tag), "entries", None)
    if beats is None:
        return info
    beats = list(beats)
    times = [float(b.time) / 1000 for b in beats]
    numbers = [int(b.beat) for b in beats]
    bpms = [float(b.tempo) / 100 for b in beats]
    valid = len(times) >= 2 and all(math.isfinite(t) and t >= 0 for t in times) and all(a < b for a, b in zip(times, times[1:])) and all(1 <= n <= 4 for n in numbers)
    downbeats = [i for i, number in enumerate(numbers) if number == 1]
    if not valid or not downbeats:
        return info
    info.update(
        available=True,
        source=Path(src).suffix.lstrip("."),
        beat_count=len(beats),
        downbeat_count=len(downbeats),
        beat_times=times,
        downbeat_indices=downbeats,
        bpms=bpms,
    )
    return info


def read_phrases(db: Any, content: Any) -> dict[str, Any]:
    """ANLZ (PSSI) からフレーズ解析概要を読む。書込はしない。"""
    info: dict[str, Any] = {"available": False, "phrase_count": 0}
    found = _analysis_tag(db, content, "PSSI", ("EXT", "2EX", "DAT"))
    if found is None:
        return info
    tag, _ = found
    content_obj = getattr(tag, "content", tag)
    entries = getattr(content_obj, "entries", None)
    entries = list(entries) if entries is not None else []
    mood = getattr(content_obj, "mood", None)
    # PSSI phrase IDs depend on mood; never treat an unknown mood as a known one.
    labels = {1: "INTRO", 5: "CHORUS", 6: "OUTRO"} if mood == 1 else (
        {1: "INTRO", **{i: "VERSE" for i in range(2, 8)}, 8: "BRIDGE", 9: "CHORUS", 10: "OUTRO"} if mood in (2, 3) else {}
    )
    sections = []
    ordered = sorted(entries, key=lambda e: int(e.beat))
    for i, entry in enumerate(ordered):
        start = int(entry.beat) - 1
        end = int(ordered[i + 1].beat if i + 1 < len(ordered) else getattr(content_obj, "end_beat", 0)) - 1
        kind = labels.get(getattr(entry, "kind", None), "UNKNOWN")
        if start >= 0 and end > start:
            if sections and sections[-1]["kind"] == kind and sections[-1]["end_beat"] == start:
                sections[-1]["end_beat"] = end
            else:
                sections.append({"start_beat": start, "end_beat": end, "kind": kind})
    info.update(
        available=True,
        mood=mood,
        sections=sections,
        phrase_count=len(entries),
        boundary_beats=sorted({int(e.beat) - 1 for e in entries if int(e.beat) >= 1}),
    )
    return info


def load_track_analysis(db: Any, content_id: str, expected_path: str | None = None) -> dict[str, Any]:
    """rekordbox の解析スナップショット。DB/ANLZ へは書き込まない。"""
    content = db.get_content(ID=content_id)
    if content is None:
        raise ValueError("rekordbox のライブラリから解析済みの曲を選んでください")
    if expected_path and Path(str(content.FolderPath)).resolve() != Path(expected_path).resolve():
        raise ValueError("選択した音源と rekordbox の登録パスが異なります。曲を選び直してください")
    grid = read_beatgrid(db, content)
    if not grid["available"]:
        raise ValueError("rekordbox のビートグリッドを取得できません。BPM / Grid を解析・保存してから再取得してください")
    phrases = read_phrases(db, content)
    boundaries = [b for b in phrases.get("boundary_beats", []) if 0 <= b < grid["beat_count"]]
    positive_bpms = sorted(b for b in grid["bpms"] if math.isfinite(b) and b > 0)
    bpm = positive_bpms[len(positive_bpms) // 2] if positive_bpms else _content_bpm(content)
    if not bpm:
        raise ValueError("rekordbox の解析済み BPM を取得できません")
    cues = []
    warnings = []
    try:
        for cue in db.get_cue(ContentID=content_id):
            if cue.InMsec is not None and cue.InMsec >= 0:
                cues.append({"time_ms": int(cue.InMsec), "kind": int(cue.Kind or 0), "comment": cue.Comment or ""})
    except Exception:
        warnings.append("既存 Cue を取得できませんでした")
    if not boundaries:
        warnings.append("フレーズ情報は未取得です。rekordbox の小節頭を基準に候補を生成します")
    return {
        "source": "REKORDBOX", "available": True, "content_id": str(content.ID),
        "title": content.Title, "bpm": bpm, "key": getattr(content, "KeyName", None),
        "beat_count": grid["beat_count"], "downbeat_count": grid["downbeat_count"],
        "beat_times": grid["beat_times"], "downbeat_indices": grid["downbeat_indices"],
        "phrase_count": len(boundaries), "phrase_boundaries": boundaries,
        "phrase_sections": [s for s in phrases.get("sections", []) if s["start_beat"] < grid["beat_count"]],
        "existing_cues": sorted(cues, key=lambda c: c["time_ms"]), "warnings": warnings,
    }
