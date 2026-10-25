"""音源指紋（再現性の基盤, 基本設計書 §9.4）。

内容ハッシュ＋サイズ＋更新時刻から決定的な指紋を作る。
同一指紋・同一 engine_version・同一 params で候補時刻が再現する（NFR-006）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_CHUNK = 1024 * 1024


def audio_fingerprint(path: str | Path) -> str:
    """ファイルの内容・サイズ・更新時刻から sha256 指紋を生成する。"""
    p = Path(path)
    stat = p.stat()
    h = hashlib.sha256()
    h.update(str(stat.st_size).encode("ascii"))
    h.update(str(int(stat.st_mtime)).encode("ascii"))
    with p.open("rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def file_analysis_inputs(
    path: str | Path, *, vocal_requested: bool = False, stem_analysis: dict | None = None,
) -> tuple[str, bytes | None, list[str]]:
    """Identify all file inputs without decoding or analysing the audio.

    Keep the fingerprint compatible with existing saved analysis runs.
    """
    fingerprint = audio_fingerprint(path)
    lyrics_payload = None
    warnings: list[str] = []
    if vocal_requested:
        lyrics = Path(path).with_suffix(".lrc")
        try:
            if lyrics.is_file():
                if lyrics.stat().st_size > 1024 * 1024:
                    warnings.append("LRCが大きすぎるため歌い始めの読み込みを省略しました。")
                else:
                    lyrics_payload = lyrics.read_bytes()
        except OSError:
            warnings.append("同名LRCを読み込めませんでした。")
        payload = lyrics_payload if lyrics_payload is not None else b"none"
        fingerprint = "sha256:" + hashlib.sha256(fingerprint.encode() + hashlib.sha256(payload).digest()).hexdigest()
    if stem_analysis is not None:
        fingerprint = "sha256:" + hashlib.sha256(
            fingerprint.encode() + json.dumps(stem_analysis, sort_keys=True).encode()
        ).hexdigest()
    return fingerprint, lyrics_payload, warnings
