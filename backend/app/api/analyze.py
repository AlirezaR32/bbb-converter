"""POST /api/recordings/analyze — validate and inspect a playback URL."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from app.bbb.inspector import RecordingInspector
from app.config import get_settings
from app.errors import AppError
from app.schemas import AnalyzeRequest, RecordingInfoOut
from app.security.fetcher import SafeFetcher
from app.security.tokens import RateLimiter
from app.security.url_guard import validate_recording_url

router = APIRouter()
_limiter = RateLimiter(per_minute=get_settings().rate_limit_per_minute)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/recordings/analyze", response_model=RecordingInfoOut)
async def analyze_recording(payload: AnalyzeRequest, request: Request):
    settings = get_settings()
    _limiter.check(_client_ip(request))

    # 1) URL validation + SSRF guard (sync, fast).
    parsed = await asyncio.to_thread(validate_recording_url, payload.url, settings)

    # 2) Network inspection in a worker thread.
    def _inspect():
        fetcher = SafeFetcher(settings)
        try:
            inspector = RecordingInspector(settings, fetcher)
            return inspector.inspect(parsed)
        finally:
            fetcher.close()

    try:
        inspection = await asyncio.to_thread(_inspect)
    except AppError:
        raise
    return RecordingInfoOut(**inspection.to_dict())
