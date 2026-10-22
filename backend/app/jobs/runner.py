"""Job execution backends.

- inline (default, zero-infrastructure): a bounded ThreadPoolExecutor inside the
  API process. Good for single-node deployments and development.
- celery: production mode with Redis broker; the same `run_job` entry point runs
  in a dedicated worker container (see docker-compose.yml).
"""

from __future__ import annotations

import atexit
import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings

log = logging.getLogger("bbb.jobs")

_executor: ThreadPoolExecutor | None = None
_celery_app = None


def _inline_executor() -> ThreadPoolExecutor:
    global _executor  # noqa: PLW0603
    if _executor is None:
        settings = get_settings()
        _executor = ThreadPoolExecutor(
            max_workers=max(1, settings.max_concurrent_jobs),
            thread_name_prefix="bbb-convert",
        )
        atexit.register(_executor.shutdown, wait=False)
    return _executor


def submit_conversion(job_id: str) -> None:
    settings = get_settings()
    if settings.job_queue == "celery":
        app = _get_celery()
        app.send_task("app.jobs.worker.convert_job", args=[job_id])
        log.info("job %s dispatched to celery", job_id)
    else:
        from app.media.pipeline import run_job

        def _run() -> None:
            try:
                run_job(job_id)
            except Exception:  # pragma: no cover - pipeline records its own errors
                log.exception("job %s crashed", job_id)

        _inline_executor().submit(_run)
        log.info("job %s submitted to inline worker", job_id)


def _get_celery():
    global _celery_app  # noqa: PLW0603
    if _celery_app is None:
        from app.jobs.celery_app import make_celery

        _celery_app = make_celery()
    return _celery_app
