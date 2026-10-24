"""Prepare an additive XML update from a fresh rekordbox collection export.

The live library is only read. Existing TRACK attributes, TEMPO and POSITION_MARK
elements are copied verbatim as XML data, and new cues use free capacity only.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
from bisect import bisect_right
import hashlib
import json
import math
import os
from pathlib import Path
import re
from uuid import uuid4
from datetime import datetime
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from ..common import loads
from ..config import get_settings
from ..domain.cue_presets import cue_preset
from ..domain.cue_targets import cue_target_label
from .adapter import AdapterError, open_rekordbox
from .cue_selection import select_export_cues
from .reader import get_content_detail, read_beatgrid


MAX_SOURCE_BYTES = 20 * 1024 * 1024
TEXT_METADATA = {"Comments": "Commnt", "Genre": "GenreName", "Composer": "ComposerName", "Remixer": "RemixerName", "Label": "LabelName", "Tonality": "KeyName"}
NUMBER_METADATA = {"DiscNumber": "DiscNo", "TrackNumber": "TrackNo", "Year": "ReleaseYear", "PlayCount": "DJPlayCount", "BitRate": "BitRate", "SampleRate": "SampleRate", "Size": "FileSize", "TotalTime": "Length"}


def xml_metadata(content) -> dict:
    metadata = {key: str(getattr(content, field, None) or "") for key, field in TEXT_METADATA.items()}
    metadata.update({key: float(getattr(content, field, None) or 0) for key, field in NUMBER_METADATA.items()})
    rating = int(getattr(content, "Rating", None) or 0)
    metadata["Rating"] = rating * 51 if 0 <= rating <= 5 else rating
    metadata["AverageBpm"] = float(getattr(content, "BPM", None) or 0) / 100
    return metadata


def parse_collection(payload: bytes) -> ET.Element:
    if len(payload) > MAX_SOURCE_BYTES or b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("20MB以下のrekordboxコレクションXMLを選んでください。")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("XMLを読み込めませんでした。rekordboxから書き出したXMLを選んでください。") from exc
    product = root.find("PRODUCT")
    if root.tag != "DJ_PLAYLISTS" or root.find("COLLECTION") is None or product is None or not product.get("Name", "").casefold().startswith("rekordbox"):
        raise ValueError("アプリの出力XMLではなく、rekordboxの「コレクションをxml形式でエクスポート」で保存したXMLを選んでください。")
    return root


def save_source(payload: bytes, filename: str, source_dir: Path) -> dict:
    root = parse_collection(payload)
    source_id = uuid4().hex
    source_dir.mkdir(parents=True, exist_ok=True)
    name = filename.replace("\\", "/").split("/")[-1][:255] or "collection.xml"
    (source_dir / f"{source_id}.xml").write_bytes(payload)
    info = {"source_id": source_id, "filename": name, "tracks": len(root.findall("COLLECTION/TRACK"))}
    (source_dir / f"{source_id}.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def source_info(source_id: str, source_dir: Path) -> tuple[dict, bytes]:
    if not re.fullmatch(r"[0-9a-f]{32}", source_id):
        raise ValueError("コレクションXMLを選び直してください。")
    try:
        return json.loads((source_dir / f"{source_id}.json").read_text(encoding="utf-8")), (source_dir / f"{source_id}.xml").read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("保存済みのコレクションXMLが見つかりません。選び直してください。") from exc


def path_key(path: str | Path) -> str:
    # Keep separate library entries for aliases/symlinks separate as well.
    return os.path.normcase(os.path.abspath(path))


def location_key(location: str) -> str:
    parts = urlsplit(location)
    if parts.scheme != "file" or parts.netloc.casefold() not in {"", "localhost"}:
        raise ValueError("ローカル音源を参照するコレクションXMLを選んでください。")
    path = unquote(parts.path)
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return path_key(path)


def current_tracks(rows: list[dict]) -> dict[str, dict]:
    """Fail on unreadable cues; an empty result must never mean unknown data."""
    settings = get_settings()
    snapshots = {}
    try:
        with open_rekordbox(path=settings.rekordbox_db_path, key=settings.rekordbox_key) as db:
            for row in rows:
                content_id = str(row["content_id"])
                detail = get_content_detail(db, content_id)
                if detail is None or not detail.get("path") or path_key(detail["path"]) != path_key(row["path"]):
                    raise ValueError("元の曲を照合できません。rekordboxライブラリから対象曲を選び直してください。")
                cues = [{field: getattr(cue, field, None) for field in ("ID", "Kind", "InMsec", "OutMsec", "Comment", "Color", "ColorTableIndex", "ActiveLoop", "rb_local_usn")}
                        for cue in db.get_cue(ContentID=content_id)]
                content = db.get_content(ID=content_id)
                snapshots[row["id"]] = {"detail": detail, "cues": sorted(cues, key=lambda cue: str(cue["ID"])),
                    "grid": read_beatgrid(db, content), "xml_metadata": xml_metadata(content), "tags": {key: getattr(content, key, None) for key in ("UUID", "ColorID", "Subtitle", "updated_at", "rb_local_usn")}}
    except AdapterError as exc:
        raise ValueError("既存Cueを照合できません。rekordboxライブラリへの接続を確認してください。") from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("既存Cueをすべて取得できないため、追加用XMLを作成できません。") from exc
    return snapshots


def _mark_signature(mark: ET.Element) -> tuple:
    try:
        kind, num = int(mark.get("Type", "0")), int(mark.get("Num", "-1"))
        start = float(mark.get("Start", "nan"))
        end = float(mark.get("End", "nan")) if kind == 4 else -1.0
        if kind not in (0, 4) or num not in range(-1, 8) or not math.isfinite(start) or start < 0 or (kind == 4 and (not math.isfinite(end) or end <= start)):
            raise ValueError
        rgb = [mark.get(key) for key in ("Red", "Green", "Blue")]
        if any(value is not None for value in rgb) and (any(value is None for value in rgb) or any(int(value) not in range(256) for value in rgb)):
            raise ValueError
        return num, round(start * 1000), round(end * 1000) if kind == 4 else -1, mark.get("Name", "")
    except (ValueError, TypeError) as exc:
        raise ValueError("既存Cueに未対応の種類・スロット・時刻があるため、この曲の追加を止めました。") from exc


def validate_grid(track: ET.Element, grid: dict) -> None:
    if not grid.get("available"):
        raise ValueError("現在の拍位置を取得できないため、グリッドを保持して追加できません。")
    try:
        segments = [(float(tempo.get("Inizio")), float(tempo.get("Bpm")), int(tempo.get("Battito"))) for tempo in track.findall("TEMPO")]
        if not segments or any(tempo.get("Metro", "4/4") != "4/4" for tempo in track.findall("TEMPO")) or any(not math.isfinite(t) or t < 0 or not math.isfinite(bpm) or bpm <= 0 or beat not in range(1, 5) for t, bpm, beat in segments) or any(a[0] >= b[0] for a, b in zip(segments, segments[1:])):
            raise ValueError
        times, bars = grid["beat_times"], grid["downbeat_indices"]
        starts = [segment[0] for segment in segments]
        for index, time in enumerate(times):
            segment_index = bisect_right(starts, time + .008) - 1
            if segment_index < 0:
                raise ValueError
            start, bpm, first = segments[segment_index]
            offset = round((time - start) * bpm / 60)
            bar_position = bisect_right(bars, index) - 1
            anchor = bars[max(0, bar_position)]
            if abs(start + offset * 60 / bpm - time) > .008 or (first - 1 + offset) % 4 != (index - anchor) % 4:
                raise ValueError
        if starts[-1] > times[-1] + .008:
            raise ValueError
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise ValueError("XMLの拍位置・小節頭が現在のグリッドと一致しません。拍情報を含む最新のコレクションXMLを書き出し直してください。") from exc


def validate_snapshot(track: ET.Element, snapshot: dict) -> None:
    detail, cues = snapshot["detail"], snapshot["cues"]
    for key, xml_key in (("title", "Name"), ("artist", "Artist"), ("album", "Album")):
        if track.get(xml_key, "") != (detail.get(key) or ""):
            raise ValueError("曲名・アーティスト・アルバムが現在のライブラリと異なります。最新のコレクションXMLを書き出し直してください。")
    for key, current in snapshot.get("xml_metadata", {}).items():
        value = track.get(key)
        if value is None:
            continue
        try:
            same = value == current if isinstance(current, str) else math.isfinite(float(value or 0)) and abs(float(value or 0) - current) <= .01
        except ValueError:
            same = False
        if not same:
            raise ValueError(f"{key}が現在の曲情報と異なります。既存の情報を保持するため、最新のコレクションXMLを書き出し直してください。")
    try:
        total = float(track.get("TotalTime", "0"))
        if not math.isfinite(total) or total <= 0:
            raise ValueError
    except ValueError as exc:
        raise ValueError("曲の長さを含むコレクションXMLを選んでください。") from exc
    if not track.findall("TEMPO"):
        raise ValueError("グリッドを保持するため、拍情報を含むコレクションXMLを書き出し直してください。")
    validate_grid(track, snapshot["grid"])
    if any(cue.get("ActiveLoop") for cue in cues):
        raise ValueError("アクティブループの状態をXMLで保持できないため、この曲への追加を止めました。")
    actual = []
    for cue in cues:
        try:
            kind, start = int(cue["Kind"]), int(cue["InMsec"])
            end = int(cue["OutMsec"]) if cue["OutMsec"] is not None else -1
            if kind not in range(9) or start < 0 or (end >= 0 and end <= start):
                raise ValueError
            actual.append((kind - 1 if kind else -1, start, end, cue.get("Comment") or ""))
        except (TypeError, ValueError) as exc:
            raise ValueError("既存Cueの形式を確認できないため、この曲への追加を止めました。") from exc
    remaining = actual[:]
    for mark in track.findall("POSITION_MARK"):
        expected = _mark_signature(mark)
        found = next((i for i, cue in enumerate(remaining) if cue[0] == expected[0] and abs(cue[1] - expected[1]) <= 1 and (cue[2] == expected[2] or cue[2] >= 0 and expected[2] >= 0 and abs(cue[2] - expected[2]) <= 1) and cue[3] == expected[3]), None)
        if found is None:
            raise ValueError("既存CueがコレクションXMLと一致しません。rekordboxで保存後、XMLを書き出し直してください。")
        remaining.pop(found)
    if remaining:
        raise ValueError("コレクションXMLに含まれていない既存Cueがあります。最新のXMLを書き出し直してください。")


def prepare_existing(repo, job_id: str, *, source_id: str, source_dir: Path, memory_candidate_ids=None, cue_colors=None) -> dict:
    info, payload = source_info(source_id, source_dir)
    source = parse_collection(payload)
    by_path: dict[str, list[ET.Element]] = {}
    for track in source.findall("COLLECTION/TRACK"):
        # Unrelated streaming entries do not affect local target matching.
        if track.get("Location", "").startswith("file:"):
            try:
                by_path.setdefault(location_key(track.get("Location")), []).append(track)
            except ValueError:
                continue
    decisions = select_export_cues(repo.list_accepted_decisions_for_job(job_id), memory_candidate_ids)
    if not decisions:
        raise ValueError("追加するCueを選んでください。")
    grouped = {}
    for decision in decisions:
        grouped.setdefault(decision["track_id"], []).append(decision)
    rows = sorted([dict(repo.get_track(track_id)) for track_id in grouped], key=lambda row: row["id"])
    if any(not Path(row["path"]).is_file() for row in rows):
        raise ValueError("元の音源が見つかりません。rekordboxの登録パスを確認してください。")
    snapshots = current_tracks(rows)
    job = repo.get_job(job_id)
    params = loads(job["params_json"]) or {}
    colors = cue_colors or {}
    if any(value is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", value) for value in colors.values()):
        raise ValueError("Cueの色を選び直してください。")
    root = ET.Element("DJ_PLAYLISTS", dict(source.attrib))
    root.append(deepcopy(source.find("PRODUCT")))
    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(rows)))
    ET.SubElement(ET.SubElement(root, "PLAYLISTS"), "NODE", Name="ROOT", Type="0", Count="0")
    items, issues, capacities = [], [], []
    settings_used = False
    for row in rows:
        title = snapshots[row["id"]]["detail"].get("title") or Path(row["path"]).name
        matches = by_path.get(path_key(row["path"]), [])
        if len(matches) != 1:
            issues.append(f"{title}: 元の音源パスに一致する曲がXML内に1件だけ必要です。最新のコレクションXMLを選んでください。")
            continue
        original = matches[0]
        try:
            validate_snapshot(original, snapshots[row["id"]])
        except ValueError as exc:
            issues.append(f"{title}: {exc}")
            continue
        target = deepcopy(original)
        # Native XML rounds TotalTime to whole seconds. A valid final saved
        # downbeat can be after that integer while still inside the audio.
        duration = float(original.get("TotalTime", "0"))
        try:
            import soundfile as sf
            actual_duration = float(sf.info(str(row["path"])).duration)
            if math.isfinite(actual_duration) and actual_duration > 0:
                duration = actual_duration
        except (ImportError, OSError, RuntimeError, ValueError):
            pass  # Retain the conservative XML bound when the header is unreadable.
        snapshots[row["id"]]["duration_sec"] = duration
        collection.append(target)
        marks = target.findall("POSITION_MARK")
        signatures = [_mark_signature(mark) for mark in marks]
        used = {num for num, *_ in signatures if num >= 0}
        if len(used) != sum(num >= 0 for num, *_ in signatures):
            issues.append(f"{title}: 既存Hot Cueのスロットが重複しています。")
        counts = Counter("MEMORY" if sig[0] == -1 else "HOT" for sig in signatures)
        if counts["MEMORY"] > 10 or counts["HOT"] > 8:
            issues.append(f"{title}: 既存Cueが上限を超えているため、保持したまま追加できません。")
        for mark, sig in zip(marks, signatures):
            color = "#" + "".join(f"{int(mark.get(key)):02x}" for key in ("Red", "Green", "Blue")) if all(mark.get(key) is not None for key in ("Red", "Green", "Blue")) else None
            items.append({"track_id": row["id"], "cue_kind": "MEMORY" if sig[0] == -1 else "HOT", "action": "KEEP", "time_ms": sig[1], "end_time_ms": sig[2] if sig[2] >= 0 else None, "slot": chr(65 + sig[0]) if sig[0] >= 0 else None, "color": color, "reason": f"既存を維持：{mark.get('Name', '')}" + ("（ループ）" if sig[2] >= 0 else "")})
        added = Counter()
        # Honor explicit Hot Cue slots before allocating any automatic slots.
        selected = sorted(grouped[row["id"]], key=lambda d: (not (d["cue_kind"] == "HOT" and d.get("slot")), d["edited_time_ms"] if d["edited_time_ms"] is not None else d["orig_time_ms"], d["candidate_id"]))
        for decision in selected:
            kind = decision["cue_kind"]
            ms = int(decision["edited_time_ms"] if decision["edited_time_ms"] is not None else decision["orig_time_ms"])
            preset = cue_preset(params, decision["cue_type"])
            item = {"track_id": row["id"], "cue_kind": kind, "time_ms": ms, "slot": None, "preset": preset, "action": "ADD", "reason": cue_target_label(decision["cue_type"], params)}
            explicit = decision.get("slot") if kind == "HOT" else None
            slot = None
            if explicit:
                text = str(explicit).strip().upper()
                slot = ord(text) - 65 if len(text) == 1 and "A" <= text <= "H" else int(text) if text in tuple(str(i) for i in range(8)) else -2
                if slot not in range(8):
                    issues.append(f"{title}: Hot CueのスロットはA〜Hで指定してください。")
                    continue
            duplicate = next((sig for sig in signatures if ((kind == "MEMORY" and sig[0] == -1) or (kind == "HOT" and sig[0] >= 0 and (slot is None or sig[0] == slot))) and abs(sig[1] - ms) <= 1 and sig[2] == -1), None)
            if duplicate is not None:
                item.update(action="SKIP", reason="同じ位置のCueがあるため追加しません（既存の名前・色を維持）", slot=chr(65 + duplicate[0]) if duplicate[0] >= 0 else None)
                items.append(item)
                continue
            conflict = None
            if ms < 0 or ms / 1000 >= duration:
                conflict = "曲の範囲内のCueを選んでください。"
            elif kind == "MEMORY" and any(sig[0] == -1 and abs(sig[1] - ms) <= 1 for sig in signatures):
                conflict = "同じ位置に既存Memory Loopがあるため上書きせず停止しました。"
            elif counts[kind] + added[kind] >= (10 if kind == "MEMORY" else 8):
                label = "Memory Cue" if kind == "MEMORY" else "Hot Cue"
                remedy = "「XMLに書き出すMemory Cueを確認」で追加対象を減らしてください。" if kind == "MEMORY" else "上の候補一覧でHot Cueの採用対象を見直してください。"
                conflict = f"既存を含めて{label}の上限に達しています。{remedy}"
            elif kind == "HOT" and slot in used:
                conflict = f"Hot Cue {chr(65 + slot)}は使用済みです。既存Cueを上書きせず停止しました。"
            if conflict:
                item.update(action="CONFLICT", reason=conflict)
                issues.append(f"{title}: {conflict}")
                items.append(item)
                continue
            if kind == "HOT":
                if slot is None:
                    slot = next(i for i in range(8) if i not in used)
                used.add(slot)
            num = slot if kind == "HOT" else -1
            item["slot"] = chr(65 + slot) if kind == "HOT" else None
            mark = ET.SubElement(target, "POSITION_MARK", Name=item["reason"], Type="0", Start=str(ms / 1000), Num=str(num))
            color = preset.get("memory_color" if kind == "MEMORY" else "hot_color", colors.get(kind)) if preset else colors.get(kind)
            if color:
                mark.attrib.update({key: str(int(color[offset:offset + 2], 16)) for key, offset in (("Red", 1), ("Green", 3), ("Blue", 5))})
            settings_used |= bool(preset)
            signatures.append((num, ms, -1, item["reason"]))
            added[kind] += 1
            items.append(item)
        capacities.append({"track_id": row["id"], "title": title, "path": row["path"], "existing_memory": counts["MEMORY"], "existing_hot": counts["HOT"], "add_memory": added["MEMORY"], "add_hot": added["HOT"]})
    actions = Counter(item["action"] for item in items)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    digest = hashlib.sha256(json.dumps({"job": job_id, "source": hashlib.sha256(payload).hexdigest(), "snapshot": snapshots, "output": hashlib.sha256(xml).hexdigest()}, sort_keys=True, default=str).encode()).hexdigest()
    return {"plan_id": uuid4().hex, "confirmation_hash": digest, "mode": "EXISTING", "add": actions["ADD"], "replace": 0, "conflict": len(issues), "preserved": actions["KEEP"], "duplicates_skipped": actions["SKIP"], "items": items, "issues": list(dict.fromkeys(issues)), "track_updates": capacities, "source_name": info["filename"], "_xml": xml, "_backup": payload, "_cue_settings_used": settings_used}


def export_existing(prepared: dict, export_root: Path, *, confirmation_hash: str, cue_colors=None) -> dict:
    if prepared["conflict"]:
        raise ValueError("追加できない曲があります。確認画面の理由を解消してください。")
    if prepared["confirmation_hash"] != confirmation_hash:
        raise ValueError("確認後にライブラリ・対象Cue・色が変わりました。追加内容をもう一度確認してください。")
    if not prepared["add"]:
        raise ValueError("追加する新しいCueはありません。同じ位置のCueは既存のまま保持されています。")
    folder = export_root / datetime.now().strftime("%Y%m%d") / uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    xml_path = folder / "rekordbox.xml"
    backup_path = folder / "original_collection.xml"
    backup_path.write_bytes(prepared["_backup"])
    xml_path.write_bytes(prepared["_xml"])
    return {"folder": str(folder), "xml_path": str(xml_path), "backup_xml_path": str(backup_path), "tracks": len(prepared["track_updates"]), "cues": prepared["add"] + prepared["preserved"], "copied": 0, "skipped": [], "cue_colors": cue_colors or {}, "cue_settings_used": prepared["_cue_settings_used"], "mode": "EXISTING", "added_cues": prepared["add"], "preserved_cues": prepared["preserved"], "duplicates_skipped": prepared["duplicates_skipped"], "warnings": ["元の音源を参照するXMLです。書き出しただけではrekordboxは更新されません。確認した対象曲だけを取り込んでください。"]}
