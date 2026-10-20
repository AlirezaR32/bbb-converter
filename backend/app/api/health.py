"""GET /api/health — liveness + capability report."""

from __future__ import annotations

import shutil

from fastapi import APIRouter

from app.config import get_settings
from app.jobs.store import active_job_count
from app.media.ffmpeg import ffmpeg_available
from app.schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
async def health():
    settings = get_settings()
    ok, version = ffmpeg_available()
    usage = shutil.disk_usage(settings.data_dir)
    return HealthOut(
        status="ok" if ok else "degraded",
        version=settings.version,
        ffmpeg_available=ok,
        ffmpeg_version=version,
        queue_mode=settings.job_queue,
        active_jobs=active_job_count(),
        storage_free_gb=round(usage.free / 1e9, 2),
        demo_mode=settings.demo_mode,
        demo_url=settings.demo_recording_url if settings.demo_mode else None,
        limits={
            "max_recording_hours": settings.max_recording_hours,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
            "max_asset_mb": settings.max_asset_mb,
            "output_ttl_hours": settings.output_ttl_hours,
        },
    )
