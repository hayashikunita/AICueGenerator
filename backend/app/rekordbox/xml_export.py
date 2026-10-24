"""rekordbox XML エクスポート（採用キューを安全に保存する）。

ライブ DB を触らず、yyyymmdd のライブラリフォルダを作成して音源を複製し、
複製先を参照する rekordbox.xml（POSITION_MARK 付き）を書き出す。
rekordbox の「rekordbox xml」ブリッジから取り込める。
"""

from __future__ import annotations

import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..common import loads
from ..domain.cue_kinds import expand_cue_kind
from ..domain.cue_targets import CUE_TARGET_LABELS


def _slot_to_num(slot: str | None, fallback: int) -> int:
    """ホットキューの slot を rekordbox の Num(0=A..7=H) に変換する。"""
    if slot:
        s = slot.strip().upper()
        if len(s) == 1 and "A" <= s <= "H":
            return ord(s) - ord("A")
        if s.isdigit():
            if 0 <= int(s) <= 7:
                return int(s)
        raise ValueError("Hot Cue のスロットは A〜H を指定してください")
    return fallback


def _track_name(row: Any) -> str:
    meta = loads(row["metadata_json"]) if row["metadata_json"] else None
    if isinstance(meta, dict):
        title = meta.get("title") or meta.get("name")
        if title:
            return str(title)
    return Path(str(row["path"])).stem


def export_rekordbox_xml(repo: Any, job_id: str, *, export_root: Path, cue_colors: dict[str, str] | None = None) -> dict[str, Any]:
    """採用キューから yyyymmdd ライブラリを作り、音源複製と rekordbox.xml を書き出す。"""
    from pyrekordbox.rbxml import RekordboxXml

    colors = dict(cue_colors or {})
    if colors and (set(colors) != {"MEMORY", "HOT"} or any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors.values())):
        raise ValueError("Cue の色は Memory Cue と Hot Cue に #RRGGBB 形式で指定してください。")

    decisions = [dict(r) for r in repo.list_accepted_decisions_for_job(job_id)]
    if not decisions:
        raise ValueError("採用キューがありません（書き出し対象なし）")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for d in decisions:
        for kind in expand_cue_kind(d["cue_kind"]):
            grouped.setdefault(d["track_id"], []).append({**d, "cue_kind": kind})

    # 出力前に Hot Cue の枠を確定し、既存の出力を変更せずに入力を検証する。
    for decs in grouped.values():
        decs.sort(key=lambda d: d["edited_time_ms"] if d["edited_time_ms"] is not None else d["orig_time_ms"])
        hot_cues = [d for d in decs if d["cue_kind"] == "HOT"]
        if len(hot_cues) > 8:
            raise ValueError("Hot Cue は 1 曲につき 8 件までです。残りを Memory Cue に変更してください。")
        used: set[int] = set()
        for d in hot_cues:
            if d.get("slot"):
                num = _slot_to_num(d["slot"], 0)
                if num in used:
                    raise ValueError(f"Hot Cue のスロット {chr(65 + num)} が重複しています")
                d["xml_num"] = num
                used.add(num)
        for d in hot_cues:
            if "xml_num" not in d:
                num = next(n for n in range(8) if n not in used)
                d["xml_num"] = num
                used.add(num)

    library = export_root / datetime.now().strftime("%Y%m%d")
    library.mkdir(parents=True, exist_ok=True)

    xml = RekordboxXml()
    copied = 0
    cue_count = 0
    track_count = 0
    skipped: list[str] = []
    memory_color_written = False

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

        for d in decs:
            time_ms = d["edited_time_ms"] if d["edited_time_ms"] is not None else d["orig_time_ms"]
            start = max(0.0, int(time_ms) / 1000)
            kind = str(d.get("cue_type") or "")
            name = CUE_TARGET_LABELS.get(kind, kind)
            mark = track.add_mark(Name=name, Type="cue", Start=start, Num=d.get("xml_num", -1))
            color = colors.get(d["cue_kind"])
            if color:
                # PositionMark's public setter omits RGB. Preserve its normal
                # cue serialization, adding RGB attributes to this new XML only.
                mark._element.attrib.update({key: str(int(color[offset:offset + 2], 16))
                                             for key, offset in (("Red", 1), ("Green", 3), ("Blue", 5))})
                if d["cue_kind"] == "MEMORY":
                    memory_color_written = True
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
        "cue_colors": colors,
        "warnings": ["Memory Cue の色も XML に記録しました。rekordbox での色の反映は未確認のため、取り込み後に確認してください。"] if memory_color_written else [],
    }
