from __future__ import annotations

import secrets


def generate_token() -> str:
    """起動ごとの一時トークン (32バイト相当のURLセーフ文字列) を生成する。"""
    return secrets.token_urlsafe(32)


def verify_token(provided: str | None, expected: str) -> bool:
    """タイミング攻撃に配慮した固定時間比較でトークンを検証する。"""
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)
