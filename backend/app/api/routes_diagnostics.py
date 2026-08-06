from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..rekordbox.diagnostics import diagnose
from ..schemas.health import RekordboxDiagnostics
from .deps import require_token

router = APIRouter(prefix="/api/v1", tags=["diagnostics"], dependencies=[Depends(require_token)])


@router.get("/diagnostics", response_model=RekordboxDiagnostics)
def diagnostics() -> RekordboxDiagnostics:
    """rekordbox 環境診断。DB を開かずプロセス/鍵/容量のみ確認する。"""
    result = diagnose(backup_dir=get_settings().data_dir)
    return RekordboxDiagnostics(
        process_running=result.rekordbox_running,
        db_key_available=result.sqlcipher_available,
        schema_supported=result.schema_supported,
        cloud_sync_enabled=None,
        writable=result.writable,
        state="ok",
    )
