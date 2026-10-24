"""rekordbox XML エクスポート（採用キューを安全に保存する）。

ライブ DB を触らず、yyyymmdd のライブラリフォルダを作成して音源を複製し、
複製先を参照する rekordbox.xml（POSITION_MARK 付き）を書き出す。
rekordbox の「rekordbox xml」ブリッジから取り込める。
"""

from __future__ import annotations

import shutil
import re
import math
import wave
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..common import loads
from ..domain.cue_kinds import CUE_LIMITS
from ..domain.cue_targets import cue_target_label
from ..domain.cue_presets import cue_preset
from .cue_selection import select_export_cues
from .metadata import track_metadata


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
    meta = track_metadata(row)
    title = meta.get("title") or meta.get("name")
    if title:
        return str(title)
    return Path(str(row["path"])).stem


def _total_time(row: Any, analysis: dict[str, Any]) -> int:
    """Cue import needs a positive TotalTime, including for legacy track refs."""
    for duration_ms in (analysis.get("duration_ms"), row["duration_ms"]):
        try:
            seconds = float(duration_ms) / 1000
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and seconds > 0:
            return math.ceil(seconds)

    path = Path(str(row["path"]))
    try:
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as audio:
                seconds = audio.getnframes() / audio.getframerate()
        else:
            import soundfile as sf
            seconds = float(sf.info(str(path)).duration)
        if math.isfinite(seconds) and seconds > 0:
            return math.ceil(seconds)
    except (ImportError, OSError, RuntimeError, ValueError, EOFError, wave.Error):
        pass
    raise ValueError(f"{_track_name(row)}: 曲の長さを取得できないためXMLを書き出せません。アプリで解析し直してください。")


def export_rekordbox_xml(repo: Any, job_id: str, *, export_root: Path, cue_colors: dict[str, str | None] | None = None,
                       memory_candidate_ids: list[str] | None = None) -> dict[str, Any]:
    """採用キューから yyyymmdd ライブラリを作り、音源複製と rekordbox.xml を書き出す。"""
    from pyrekordbox.rbxml import RekordboxXml

    colors = dict(cue_colors or {})
    job = repo.get_job(job_id)
    params = loads(job["params_json"]) if job is not None else {}
    settings_used = False
    if colors and (set(colors) != {"MEMORY", "HOT"} or any(not (key == "MEMORY" and c is None) and (not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c)) for key, c in colors.items())):
        raise ValueError("Cue の色は Memory Cue と Hot Cue に #RRGGBB 形式で指定してください。")

    decisions = [dict(r) for r in repo.list_accepted_decisions_for_job(job_id)]
    if not decisions:
        raise ValueError("採用キューがありません（書き出し対象なし）")

    grouped: dict[str, list[dict[str, Any]]] = {}
    output_cues = select_export_cues(decisions, memory_candidate_ids)
    for d in output_cues:
        grouped.setdefault(d["track_id"], []).append(d)
    if not grouped:
        raise ValueError("XMLに書き出すCueを1つ以上選んでください。")
    omitted_memory = sum(d["cue_kind"] in {"MEMORY", "BOTH"} for d in decisions) - sum(d["cue_kind"] == "MEMORY" for d in output_cues)

    analyses = {r["track_id"]: loads(r["analysis_json"]) if r["analysis_json"] else {}
                for r in repo.list_job_tracks(job_id)}
    total_times: dict[str, int] = {}
    # Validate every track before creating output files, then allocate Hot Cue slots.
    for track_id, decs in grouped.items():
        row = repo.get_track(track_id)
        if row is not None and Path(str(row["path"])).is_file():
            total_times[track_id] = _total_time(row, analyses.get(track_id) or {})
        for kind, limit in CUE_LIMITS.items():
            count = sum(d["cue_kind"] == kind for d in decs)
            if count > limit:
                row = repo.get_track(track_id)
                name = f"{_track_name(row)} [{row['content_id']}]" if row is not None else track_id
                label = "Memory Cue" if kind == "MEMORY" else "Hot Cue"
                raise ValueError(f"{name}: XMLに出力する{label}が{count}件あります。1曲につき{limit}件まで選んでください。採用した候補はそのまま残せます。")
        decs.sort(key=lambda d: d["edited_time_ms"] if d["edited_time_ms"] is not None else d["orig_time_ms"])
        hot_cues = [d for d in decs if d["cue_kind"] == "HOT"]
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

    library = export_root / datetime.now().strftime("%Y%m%d") / uuid4().hex
    library.mkdir(parents=True, exist_ok=False)

    xml = RekordboxXml()
    copied = 0
    cue_count = 0
    track_count = 0
    skipped: list[str] = []
    memory_color_written = False
    used_names: set[str] = set()

    for track_id, decs in grouped.items():
        row = repo.get_track(track_id)
        if row is None:
            skipped.append(f"{track_id}: トラック情報なし")
            continue
        src = Path(str(row["path"]))
        if not src.is_file():
            skipped.append(f"{src.name}: 音源が見つかりません")
            continue

        name = src.name
        suffix = 1
        while name.casefold() in used_names or name.casefold() == "rekordbox.xml":
            name = f"{src.stem} ({suffix}){src.suffix}"
            suffix += 1
        used_names.add(name.casefold())
        dest = library / name
        try:
            shutil.copy2(src, dest)
            copied += 1
        except OSError as exc:
            skipped.append(f"{src.name}: 複製失敗 ({exc})")
            continue

        kwargs: dict[str, Any] = {"Name": _track_name(row), "TotalTime": total_times[track_id]}
        metadata = track_metadata(row)
        for field, attribute in (("artist", "Artist"), ("album", "Album")):
            if metadata.get(field):
                kwargs[attribute] = str(metadata[field])
        track = xml.add_track(str(dest), **kwargs)
        track_count += 1

        for d in decs:
            time_ms = d["edited_time_ms"] if d["edited_time_ms"] is not None else d["orig_time_ms"]
            start = max(0.0, int(time_ms) / 1000)
            kind = str(d.get("cue_type") or "")
            name = cue_target_label(kind, params)
            mark = track.add_mark(Name=name, Type="cue", Start=start, Num=d.get("xml_num", -1))
            preset = cue_preset(params or {}, kind)
            if preset:
                settings_used = True
            color = preset.get("memory_color" if d["cue_kind"] == "MEMORY" else "hot_color", colors.get(d["cue_kind"])) if preset else colors.get(d["cue_kind"])
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

    warnings = ["Memory Cue の色も XML に記録しました。rekordbox での色の反映は未確認のため、取り込み後に確認してください。"] if memory_color_written else []
    if omitted_memory:
        warnings.append(f"採用済みMemory Cueのうち{omitted_memory}件は今回のXMLには含めていません。候補・採用状態は変更していません。")
    return {
        "folder": str(library),
        "xml_path": str(xml_path),
        "tracks": track_count,
        "cues": cue_count,
        "copied": copied,
        "skipped": skipped,
        "cue_colors": colors,
        "cue_settings_used": settings_used,
        "warnings": warnings,
    }
