from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RekordboxDiagnostics(BaseModel):
    """rekordbox 環境診断の結果。詳細判定は P0/adapter 実装で埋める。"""

    process_running: bool | None = None
    db_key_available: bool | None = None
    schema_supported: bool | None = None
    cloud_sync_enabled: bool | None = None
    writable: bool = False
    # 未実装の診断項目は "not_implemented" とする（skeleton段階）。
    state: Literal["ok", "not_implemented", "error"] = "not_implemented"


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_name: str
    app_version: str
    schema_version: int
    rekordbox: RekordboxDiagnostics
