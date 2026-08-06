from __future__ import annotations

import socket
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes_candidates import router as candidates_router
from .api.routes_diagnostics import router as diagnostics_router
from .api.routes_health import router as health_router
from .api.routes_jobs import router as jobs_router
from .api.routes_write import router as write_router
from .api.routes_ws import router as ws_router
from .config import get_settings
from .jobs.manager import JobManager
from .persistence.db import init_db
from .security import generate_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db(settings.db_path)
    # 起動ごとに新しいマネージャ（executor）を用意する。
    app.state.manager = JobManager(settings.db_path)
    try:
        yield
    finally:
        app.state.manager.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

    # 起動ごとの一時トークン。REST/WS で検証する。
    app.state.token = generate_token()
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
    print("  (127.0.0.1 限定。トークンは起動ごとに変わります)")
    print("=" * 72)

    if settings.open_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=settings.host, port=port)


if __name__ == "__main__":
    main()
