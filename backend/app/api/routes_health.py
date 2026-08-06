from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..persistence.db import SCHEMA_VERSION
from ..schemas.health import HealthResponse, RekordboxDiagnostics
from .deps import require_token

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_token),
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        app_version=settings.app_version,
        schema_version=SCHEMA_VERSION,
        # rekordbox 診断は P0/adapter 実装で埋める。
        rekordbox=RekordboxDiagnostics(state="not_implemented"),
    )
