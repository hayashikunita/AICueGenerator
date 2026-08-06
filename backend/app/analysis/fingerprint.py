"""音源指紋（再現性の基盤, 基本設計書 §9.4）。

内容ハッシュ＋サイズ＋更新時刻から決定的な指紋を作る。
同一指紋・同一 engine_version・同一 params で候補時刻が再現する（NFR-006）。
"""

from __future__ import annotations

import hashlib
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
