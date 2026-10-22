"""Celery application factory (production queue mode)."""

from __future__ import annotations

import os

from celery import Celery


def make_celery() -> Celery:
    broker = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    app = Celery(
        "bbb_converter",
        broker=broker,
        backend=broker,
        include=["app.jobs.worker"],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=20,
        task_time_limit=int(os.environ.get("FFMPEG_TIMEOUT_S", "10800")) + 600,
        task_soft_time_limit=int(os.environ.get("FFMPEG_TIMEOUT_S", "10800")),
        beat_schedule={
            "cleanup-expired-jobs": {
                "task": "app.jobs.worker.cleanup_task",
                "schedule": float(os.environ.get("CLEANUP_INTERVAL_MINUTES", "10")) * 60.0,
            },
        },
    )
    return app
