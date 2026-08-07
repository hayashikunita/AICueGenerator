from __future__ import annotations

import os
import secrets
from pathlib import Path


def generate_token() -> str:
    """32バイト相当のURLセーフなランダムトークンを生成する。"""
    return secrets.token_urlsafe(32)


def resolve_token(*, override: str | None, store_path: Path) -> str:
    """トークンを解決する。優先順位は override > 保存済み > 新規生成(保存)。

    再起動ごとにトークンが変わると開いているタブが 401 になるため、
    ローカル (127.0.0.1 限定) の単一利用者ツールとしてディスクに保存して再利用する。
    """
    if override:
        return override
    if store_path.exists():
        existing = store_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = generate_token()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(token, encoding="utf-8")
    try:
        os.chmod(store_path, 0o600)
    except OSError:
        pass
    return token


def verify_token(provided: str | None, expected: str) -> bool:
    """タイミング攻撃に配慮した固定時間比較でトークンを検証する。"""
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)
