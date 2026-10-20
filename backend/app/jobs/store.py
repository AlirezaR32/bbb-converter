"""Job store: creation, status transitions, listing, deletion."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session as db_session
from app.errors import CONCURRENCY_LIMIT, QUOTA_EXCEEDED, JobError, ProcessingError
from app.models import ConversionJob, utcnow


def create_job(
    *,
    inspection: dict,
    source_url: str,
    fmt: str,
    include_webcam_pip: bool,
    client_ip: str,
) -> ConversionJob:
    """Persist a new conversion job (limits enforced) and return it."""
    settings = get_settings()
    db = db_session()
    try:
        active = db.scalar(
            select(func.count()).select_from(ConversionJob).where(
                ConversionJob.status.in_(ConversionJob.ACTIVE_STATUSES)
            )
        ) or 0
        if active >= settings.max_concurrent_jobs:
            raise JobError(
                CONCURRENCY_LIMIT,
                f"The server is already processing {active} conversion(s) (limit "
                f"{settings.max_concurrent_jobs}). Please try again in a few minutes.",
                http_status=429,
            )
        per_ip = db.scalar(
            select(func.count()).select_from(ConversionJob).where(
                ConversionJob.status.in_(ConversionJob.ACTIVE_STATUSES),
                ConversionJob.client_ip == client_ip,
            )
        ) or 0
        if per_ip >= settings.max_jobs_per_ip:
            raise JobError(
                CONCURRENCY_LIMIT,
                f"You already have {per_ip} conversions in progress (limit "
                f"{settings.max_jobs_per_ip}). Cancel one to continue.",
                http_status=429,
            )
        # storage quota: total finished-but-unexpired output size
        quota_used = db.scalar(
            select(func.coalesce(func.sum(ConversionJob.output_size), 0)).where(
                ConversionJob.status == "completed"
            )
        ) or 0
        if quota_used > settings.storage_quota_gb * 1024**3:
            raise JobError(
                QUOTA_EXCEEDED,
                "The server's output storage quota is full. Expired outputs are cleaned "
                "up automatically; please try again later.",
                http_status=507,
            )

        strategy = (inspection.get("strategy") or {}).get("id", "")
        job = ConversionJob(
            source_url=source_url,
            server_host=inspection.get("server_host", ""),
            meeting_id=inspection.get("meeting_id", ""),
            playback_version=inspection.get("playback_version", ""),
            title=inspection.get("title", ""),
            duration_seconds=inspection.get("duration_seconds", 0.0),
            format=fmt,
            strategy=strategy,
            include_webcam_pip=include_webcam_pip,
            assets_json=inspection,
            fidelity_notes=(inspection.get("strategy") or {}).get("limitations", []),
            status="queued",
            stage="queued",
            client_ip=client_ip,
            expires_at=utcnow() + timedelta(hours=settings.output_ttl_hours),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def get_job(job_id: str) -> ConversionJob:
    db = db_session()
    try:
        job = db.get(ConversionJob, job_id)
        if job is None:
            raise JobError("JOB_NOT_FOUND", "This conversion job does not exist (it may have been deleted or expired).")
        return job
    finally:
        db.close()


def list_jobs(limit: int = 20) -> list[ConversionJob]:
    db = db_session()
    try:
        stmt = select(ConversionJob).order_by(ConversionJob.created_at.desc()).limit(min(limit, 100))
        return list(db.scalars(stmt))
    finally:
        db.close()


def request_cancel(job_id: str) -> ConversionJob:
    """Mark a job canceled. The worker checks this flag between steps."""
    db = db_session()
    try:
        job = db.get(ConversionJob, job_id)
        if job is None:
            raise JobError("JOB_NOT_FOUND", "This conversion job does not exist.")
        if job.status in ("queued", "running"):
            job.canceled = True
            job.status = "canceled"
            job.stage = "done"
            job.error_code = "CANCELED"
            job.error_message = "The job was canceled by the user."
            job.finished_at = utcnow()
            db.add(job)
            db.commit()
            db.refresh(job)
        return job
    finally:
        db.close()


def delete_job(job_id: str) -> dict:
    """Remove a job row + its output/work files. Cancels it first when running."""
    settings = get_settings()
    job = get_job(job_id)
    if job.is_active:
        request_cancel(job_id)
        job = get_job(job_id)
    import shutil

    shutil.rmtree(settings.work_dir / job_id, ignore_errors=True)
    if job.output_filename:
        (settings.output_dir / job.output_filename).unlink(missing_ok=True)
    db = db_session()
    try:
        j = db.get(ConversionJob, job_id)
        if j is not None:
            db.delete(j)
            db.commit()
    finally:
        db.close()
    return {"id": job_id, "deleted": True, "was_canceled": job.status == "canceled"}


def cleanup_expired() -> int:
    """Delete expired jobs and their files. Returns number purged."""
    settings = get_settings()
    now = utcnow()
    db = db_session()
    purged = 0
    try:
        stmt = select(ConversionJob).where(
            ConversionJob.expires_at.is_not(None),
            ConversionJob.expires_at < now,
        )
        for job in db.scalars(stmt):
            import shutil

            shutil.rmtree(settings.work_dir / job.id, ignore_errors=True)
            if job.output_filename:
                (settings.output_dir / job.output_filename).unlink(missing_ok=True)
            db.delete(job)
            purged += 1
        if purged:
            db.commit()
    finally:
        db.close()
    return purged


def expire_stale_running(stale_after_minutes: float = 240.0) -> int:
    """Fail jobs stuck in running state (e.g. worker crash)."""
    db = db_session()
    n = 0
    try:
        cutoff = utcnow() - timedelta(minutes=stale_after_minutes)
        stmt = select(ConversionJob).where(
            ConversionJob.status == "running",
            ConversionJob.updated_at < cutoff,
        )
        for job in db.scalars(stmt):
            job.status = "failed"
            job.error_code = "INTERNAL_ERROR"
            job.error_message = "The worker stopped responding; the job was marked as failed."
            job.finished_at = utcnow()
            db.add(job)
            n += 1
        if n:
            db.commit()
    finally:
        db.close()
    return n


def active_job_count() -> int:
    db = db_session()
    try:
        return db.scalar(
            select(func.count()).select_from(ConversionJob).where(
                ConversionJob.status.in_(ConversionJob.ACTIVE_STATUSES)
            )
        ) or 0
    finally:
        db.close()
