from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header, HTTPException, Query, Request, status

from ..config import get_settings
from ..jobs.manager import JobManager
from ..persistence.repositories import Repository
from ..security import verify_token


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """`Authorization: Bearer <起動トークン>` を検証する依存。"""
    expected: str = request.app.state.token
    provided: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[len("bearer ") :].strip()
    if not verify_token(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing token",
        )


def require_token_query(
    request: Request,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """ヘッダに加えクエリ `?token=` でも検証する（<audio> はヘッダを送れないため）。"""
    expected: str = request.app.state.token
    provided: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[len("bearer ") :].strip()
    elif token:
        provided = token
    if not verify_token(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing token",
        )


def get_manager(request: Request) -> JobManager:
    return request.app.state.manager


def get_repo() -> Iterator[Repository]:
    repo = Repository(get_settings().db_path)
    try:
        yield repo
    finally:
        repo.close()

