"""Celery tasks (production queue mode)."""

from __future__ import annotations

import logging

log = logging.getLogger("bbb.worker")


def register(app) -> None:  # noqa: ANN001
    @app.task(name="app.jobs.worker.convert_job", ignore_result=True, max_retries=0)
    def convert_job(job_id: str) -> None:
        from app.media.pipeline import run_job

        log.info("celery worker processing job %s", job_id)
        run_job(job_id)

    @app.task(name="app.jobs.worker.cleanup_task", ignore_result=True)
    def cleanup_task() -> None:
        from app.jobs import store

        purged = store.cleanup_expired()
        stale = store.expire_stale_running()
        if purged or stale:
            log.info("cleanup: purged=%s stale=%s", purged, stale)


register_tasks = register
