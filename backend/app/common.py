"""共通ユーティリティ（ID・時刻・JSON）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

# 解析エンジンのバージョン。候補の再現性・キャッシュ判定に用いる（§9.4）。
ENGINE_VERSION = "0.7.0"


def new_id() -> str:
    """32桁の16進 UUID。"""
    return uuid.uuid4().hex


def utcnow_iso() -> str:
    """UTC ISO8601 文字列。"""
    return datetime.now(timezone.utc).isoformat()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def loads(text: str | None) -> Any:
    return json.loads(text) if text else None
