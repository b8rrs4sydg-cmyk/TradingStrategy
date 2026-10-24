"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.core.logging_config import install as install_json_logging
from app.routers import admin, airports, health, holidays, metrics, plans, search

install_json_logging()


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
    app.include_router(airports.router)
    app.include_router(search.router)
    app.include_router(plans.router)
    app.include_router(metrics.router)
    app.include_router(admin.router)
    return app


app = create_app()
