"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.routers import health, holidays


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Smart Flight Finder API",
        version=__version__,
        description="進階機票搜尋與策略規劃系統 — Phase 1 API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(holidays.router)
    return app


app = create_app()
