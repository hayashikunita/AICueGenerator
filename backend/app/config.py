from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリ設定。環境変数プレフィックス AICUE_ で上書き可能。"""

    model_config = SettingsConfigDict(env_prefix="AICUE_", env_file=".env", extra="ignore")

    app_name: str = "rekordbox AI Cue Generator"
    app_version: str = "0.1.0"

    # 待受は 127.0.0.1 限定。port=0 は起動時にランダム空きポートへバインドする。
    host: str = "127.0.0.1"
    port: int = 0

    # 設定・解析キャッシュ・監査ログを保存するアプリ専用ディレクトリ。
    data_dir: Path = Path.home() / ".aicuegenerator"

    open_browser: bool = True

    # 開発時 (Vite dev server) に許可する Origin。本番は同一Origin配信のため不要。
    dev_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def static_dir(self) -> Path:
        # 本番配布時に React build を配置する場所。
        return Path(__file__).resolve().parent.parent / "static"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
