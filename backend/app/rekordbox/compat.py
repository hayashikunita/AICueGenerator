from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


def schema_fingerprint(table_columns: dict[str, list[str]]) -> str:
    """テーブル名→カラム名一覧から決定的なスキーマ指紋(sha256)を計算する。

    未知スキーマ検出と許可リスト照合に用いる (基本設計書 §10.3)。
    """
    canonical = {name: sorted(cols) for name, cols in sorted(table_columns.items())}
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CompatEntry:
    """書き込み試験に合格した組み合わせ (基本設計書 §10.3)。"""

    rekordbox_version: str
    pyrekordbox_version: str
    schema_fingerprint: str
    # 書込を許可する音源形式。
    writable_formats: frozenset[str] = field(
        default_factory=lambda: frozenset({"WAV", "AIFF", "FLAC", "MP3_CBR"})
    )


@dataclass(frozen=True)
class CompatMatrix:
    """許可リスト。P0 スパイク (S1-S9) 合格後に実値を追加する。"""

    entries: tuple[CompatEntry, ...] = ()

    def find(self, schema_fp: str) -> CompatEntry | None:
        for entry in self.entries:
            if entry.schema_fingerprint == schema_fp:
                return entry
        return None

    def is_supported(self, schema_fp: str) -> bool:
        return self.find(schema_fp) is not None

    def is_writable_format(self, schema_fp: str, fmt: str) -> bool:
        entry = self.find(schema_fp)
        return bool(entry) and fmt in entry.writable_formats


# 初期状態は空 = すべて read-only。P0 合格後にエントリを追加して書込を有効化する。
DEFAULT_MATRIX = CompatMatrix()
