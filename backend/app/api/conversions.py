"""Conversion job endpoints: create, poll, SSE stream, download, delete."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.bbb.inspector import RecordingInspector
from app.config import get_settings
from app.errors import AppError, JobError
from app.jobs import store
from app.jobs.runner import submit_conversion
from app.schemas import CreateJobRequest, JobListOut, JobOut
from app.security.fetcher import SafeFetcher
from app.security.tokens import RateLimiter, sign_download_token, verify_download_token
from app.security.url_guard import validate_recording_url

router = APIRouter()
_limiter = RateLimiter(per_minute=get_settings().rate_limit_per_minute * 3)

FORMAT_MEDIA_TYPES = {"mp4": "video/mp4", "webm": "video/webm", "mp3": "audio/mpeg"}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _job_to_out(job, base_url: str = "") -> JobOut:
    data = job.to_dict()
    if job.status == "completed" and job.output_filename:
        token, expires = sign_download_token(get_settings(), job.id)
        data["download"] = {
            "url": f"{base_url}/api/conversions/{job.id}/download?token={token}",
            "token": token,
            "expires_at": expires,
            "filename": _download_name(job),
        }
    return JobOut(**data)


def _download_name(job) -> str:
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in (job.title or job.meeting_id))[:60].strip(" ._")
    return f"{safe or 'bbb-recording'}.{job.format}"


# ---------------------------------------------------------------------------
@router.post("/conversions", response_model=JobOut, status_code=202)
async def create_conversion(payload: CreateJobRequest, request: Request):
    settings = get_settings()
    ip = _client_ip(request)
    _limiter.check(f"create:{ip}")

    parsed = await asyncio.to_thread(validate_recording_url, payload.url, settings)

    def _inspect():
        fetcher = SafeFetcher(settings)
        try:
            return RecordingInspector(settings, fetcher).inspect(parsed)
        finally:
            fetcher.close()

    inspection = await asyncio.to_thread(_inspect)
    strategy = (inspection.strategy or {}).get("id")
    if strategy == "unsupported":
        raise AppError(
            "UNSUPPORTED_RECORDING",
            inspection.strategy.get("explanation", "This recording cannot be converted."),
            http_status=422,
            details={"strategy": inspection.strategy, "assets": inspection.assets_dict()},
        )

    job = await asyncio.to_thread(
        store.create_job,
        inspection=inspection.to_dict(internal=True),
        source_url=parsed.original_url,
        fmt=payload.format,
        include_webcam_pip=payload.include_webcam_pip,
        client_ip=ip,
    )
    await asyncio.to_thread(submit_conversion, job.id)
    return _job_to_out(job)


@router.get("/conversions", response_model=JobListOut)
async def list_conversions():
    jobs = await asyncio.to_thread(store.list_jobs, 20)
    return JobListOut(jobs=[_job_to_out(j) for j in jobs])


@router.get("/conversions/{job_id}", response_model=JobOut)
async def get_conversion(job_id: str):
    job = await asyncio.to_thread(store.get_job, job_id)
    return _job_to_out(job)


@router.delete("/conversions/{job_id}")
async def delete_conversion(job_id: str):
    result = await asyncio.to_thread(store.delete_job, job_id)
    return result


# ---------------------------------------------------------------------------
@router.get("/conversions/{job_id}/events")
async def job_events(job_id: str):
    """Server-Sent Events stream with real job progress."""
    store.get_job(job_id)  # 404 early

    async def _stream():
        last_payload = None
        heartbeat = 0.0
        ticks = 0
        while True:
            try:
                job = await asyncio.to_thread(store.get_job, job_id)
            except JobError:
                yield f"event: end\ndata: {json.dumps({'error': {'code': 'JOB_NOT_FOUND'}})}\n\n"
                return
            payload = json.dumps({
                "status": job.status,
                "stage": job.stage,
                "progress": round(job.progress, 4),
                "progress_detail": job.progress_detail,
                "error": {"code": job.error_code, "message": job.error_message} if job.error_code else None,
            })
            if payload != last_payload:
                last_payload = payload
                yield f"event: progress\ndata: {payload}\n\n"
            if job.is_terminal:
                yield f"event: end\ndata: {payload}\n\n"
                return
            # heartbeat comment every ~15s keeps proxies from closing the stream
            ticks += 1
            if ticks % 30 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/conversions/{job_id}/download")
async def download_conversion(job_id: str, token: str = ""):
    settings = get_settings()
    verify_download_token(settings, job_id, token)
    job = await asyncio.to_thread(store.get_job, job_id)
    if job.status != "completed" or not job.output_filename:
        raise JobError("JOB_NOT_COMPLETED", "This job has no completed output to download yet.", http_status=409)
    path = settings.output_dir / job.output_filename
    if not path.exists():
        raise JobError("JOB_NOT_FOUND", "The output file has expired or was removed.", http_status=410)
    return FileResponse(
        path,
        media_type=FORMAT_MEDIA_TYPES.get(job.format, "application/octet-stream"),
        filename=_download_name(job),
    )
