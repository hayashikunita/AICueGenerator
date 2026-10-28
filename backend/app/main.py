from __future__ import annotations

import socket
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes_audio import router as audio_router
from .api.routes_candidates import router as candidates_router
from .api.routes_diagnostics import router as diagnostics_router
from .api.routes_health import router as health_router
from .api.routes_jobs import router as jobs_router
from .api.routes_rekordbox import router as rekordbox_router
from .api.routes_write import router as write_router
from .api.routes_ws import router as ws_router
from .config import get_settings
from .jobs.manager import JobManager
from .persistence.db import init_db
from .persistence.repositories import Repository
from .rekordbox.metadata import backfill_track_metadata
from .rekordbox.adapter import initialize_rekordbox
from .security import resolve_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db(settings.db_path)
    if settings.analysis_parallelism > 1:
        initialize_rekordbox()
    with Repository(settings.db_path) as repo:
        backfill_track_metadata(repo)
    # 起動ごとに新しいマネージャ（executor）を用意する。
    app.state.manager = JobManager(settings.db_path)
    try:
        yield
    finally:
        app.state.manager.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

    # トークンは data_dir に保存して再起動後も再利用する（AICUE_TOKEN で上書き可）。
    app.state.token = resolve_token(override=settings.token, store_path=settings.token_path)
    # lifespan 未起動でも参照できるよう既定を用意（lifespan 起動時に差し替え）。
    app.state.manager = JobManager(settings.db_path)

    # 開発時 Vite dev server からのアクセスのみ許可（本番は同一Origin配信）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dev_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(diagnostics_router)
    app.include_router(jobs_router)
    app.include_router(candidates_router)
    app.include_router(audio_router)
    app.include_router(rekordbox_router)
    app.include_router(write_router)
    app.include_router(ws_router)

    # 本番配布時のみ React build を同一Origin配信する。
    if settings.static_dir.exists():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")

    return app


app = create_app()


def _pick_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def main() -> None:
    settings = get_settings()
    port = settings.port or _pick_free_port(settings.host)
    token: str = app.state.token
    url = f"http://{settings.host}:{port}/?token={token}"

    print("=" * 72)
    print(f"  {settings.app_name} v{settings.app_version}")
    print(f"  URL   : {url}")
    print(f"  Token : {token}")
    print("  (127.0.0.1 限定。トークンは保存され再起動後も同じです)")
    print("=" * 72)

    if settings.open_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=settings.host, port=port)


if __name__ == "__main__":
    main()
