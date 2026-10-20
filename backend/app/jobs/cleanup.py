"""Background maintenance loop for inline (non-Celery) mode."""

from __future__ import annotations

import logging
import threading
import time

from app.config import get_settings

log = logging.getLogger("bbb.cleanup")
_started = False


def _loop() -> None:
    settings = get_settings()
    interval = max(60.0, settings.cleanup_interval_minutes * 60.0)
    while True:
        time.sleep(interval)
        try:
            from app.jobs import store

            purged = store.cleanup_expired()
            stale = store.expire_stale_running()
            if purged or stale:
                log.info("cleanup: purged=%s stale=%s", purged, stale)
        except Exception:  # pragma: no cover
            log.exception("cleanup cycle failed")


def start_cleanup_loop() -> None:
    global _started  # noqa: PLW0603
    if _started:
        return
    _started = True
    t = threading.Thread(target=_loop, name="bbb-cleanup", daemon=True)
    t.start()
    log.info("cleanup loop started")
