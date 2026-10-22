"""FastAPI application: routes + lifespan (demo fixtures, cleanup loop, worker)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import analyze, conversions, health
from app.config import get_settings

log = logging.getLogger("bbb.main")


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    e = exc  # AppError
    return JSONResponse(
        status_code=e.http_status,
        content={"error": {"code": e.code, "message": e.message, "details": e.details or {}}},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    from app.db import init_db

    init_db()

    if settings.demo_mode:
        from app.demo.fixtures import ensure_demo_recording

        try:
            ensure_demo_recording(settings)
            log.info("demo recording ready at %s", settings.demo_recording_url)
        except Exception:  # pragma: no cover
            log.exception("failed to generate demo recording")

    if settings.job_queue == "inline":
        from app.jobs.cleanup import start_cleanup_loop

        start_cleanup_loop()

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
    )

    from app.errors import AppError

    app.add_exception_handler(AppError, _app_error_handler)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
    app.add_middleware(GZipMiddleware, minimum_size=2048)

    app.include_router(analyze.router, prefix="/api")
    app.include_router(conversions.router, prefix="/api")
    app.include_router(health.router, prefix="/api")

    if settings.demo_mode:
        settings.demo_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/demo",
            StaticFiles(directory=str(settings.demo_dir), html=True),
            name="demo",
        )

    return app


app = create_app()
