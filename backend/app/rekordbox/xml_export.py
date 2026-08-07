"""rekordbox XML エクスポート（採用キューを安全に保存する）。

ライブ DB を触らず、yyyymmdd のライブラリフォルダを作成して音源を複製し、
複製先を参照する rekordbox.xml（POSITION_MARK 付き）を書き出す。
rekordbox の「rekordbox xml」ブリッジから取り込める。
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..common import loads


def _slot_to_num(slot: str | None, fallback: int) -> int:
    """ホットキューの slot を rekordbox の Num(0=A..7=H) に変換する。"""
    if slot:
        s = slot.strip().upper()
        if len(s) == 1 and "A" <= s <= "H":
            return ord(s) - ord("A")
        if s.isdigit():
            return max(0, min(7, int(s)))
    return max(0, min(7, fallback))


def _track_name(row: Any) -> str:
    meta = loads(row["metadata_json"]) if row["metadata_json"] else None
    if isinstance(meta, dict):
        title = meta.get("title") or meta.get("name")
        if title:
            return str(title)
    return Path(str(row["path"])).stem


def export_rekordbox_xml(repo: Any, job_id: str, *, export_root: Path) -> dict[str, Any]:
    """採用キューから yyyymmdd ライブラリを作り、音源複製と rekordbox.xml を書き出す。"""
    from pyrekordbox.rbxml import RekordboxXml

    decisions = [dict(r) for r in repo.list_accepted_decisions_for_job(job_id)]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for d in decisions:
        grouped.setdefault(d["track_id"], []).append(d)

    library = export_root / datetime.now().strftime("%Y%m%d")
    library.mkdir(parents=True, exist_ok=True)

    xml = RekordboxXml()
    copied = 0
    cue_count = 0
    track_count = 0
    skipped: list[str] = []

    for track_id, decs in grouped.items():
        row = repo.get_track(track_id)
        if row is None:
            skipped.append(f"{track_id}: トラック情報なし")
            continue
        src = Path(str(row["path"]))
        if not src.is_file():
            skipped.append(f"{src.name}: 音源が見つかりません")
            continue

        dest = library / src.name
        try:
            shutil.copy2(src, dest)
            copied += 1
        except OSError as exc:
            skipped.append(f"{src.name}: 複製失敗 ({exc})")
            continue

        kwargs: dict[str, Any] = {"Name": _track_name(row)}
        if row["duration_ms"]:
            kwargs["TotalTime"] = int(round(int(row["duration_ms"]) / 1000))
        track = xml.add_track(str(dest), **kwargs)
        track_count += 1

        hot_index = 0
        for d in sorted(decs, key=lambda x: (x["edited_time_ms"] or x["orig_time_ms"])):
            time_ms = d["edited_time_ms"] if d["edited_time_ms"] is not None else d["orig_time_ms"]
            start = max(0.0, int(time_ms) / 1000)
            name = str(d.get("cue_type") or "")
            if str(d["cue_kind"]).upper() == "HOT":
                num = _slot_to_num(d.get("slot"), hot_index)
                hot_index += 1
                track.add_mark(Name=name, Type="cue", Start=start, Num=num)
            else:
                track.add_mark(Name=name, Type="cue", Start=start, Num=-1)
            cue_count += 1

    xml_path = library / "rekordbox.xml"
    xml.save(str(xml_path))

    return {
        "folder": str(library),
        "xml_path": str(xml_path),
        "tracks": track_count,
        "cues": cue_count,
        "copied": copied,
        "skipped": skipped,
    }
