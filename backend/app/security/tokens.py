"""HMAC-signed, expiring download tokens + simple per-IP rate limiting."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque

from app.config import Settings
from app.errors import INVALID_TOKEN, RATE_LIMITED, TOKEN_EXPIRED, JobError


def _sign(settings: Settings, payload: str) -> str:
    mac = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256)
    return mac.hexdigest()[:32]


def sign_download_token(settings: Settings, job_id: str, ttl_seconds: int = 3600) -> tuple[str, int]:
    expires = int(time.time()) + ttl_seconds
    payload = f"{job_id}.{expires}"
    return f"{expires}.{_sign(settings, payload)}", expires


def verify_download_token(settings: Settings, job_id: str, token: str) -> None:
    if not token or "." not in token:
        raise JobError(INVALID_TOKEN, "Missing or malformed download token.", http_status=403)
    try:
        expires_s, sig = token.split(".", 1)
        expires = int(expires_s)
    except ValueError as exc:
        raise JobError(INVALID_TOKEN, "Malformed download token.", http_status=403) from exc
    if expires < int(time.time()):
        raise JobError(TOKEN_EXPIRED, "This download link has expired. Request a fresh one from the job status.", http_status=403)
    expected = _sign(settings, f"{job_id}.{expires}")
    if not hmac.compare_digest(expected, sig):
        raise JobError(INVALID_TOKEN, "Download token is not valid for this job.", http_status=403)


class RateLimiter:
    """In-process sliding-window rate limiter (per API worker)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        dq = self._hits[key]
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= self.per_minute:
            raise JobError(
                RATE_LIMITED,
                f"Too many requests. Limit is {self.per_minute} per minute; retry shortly.",
                http_status=429,
            )
        dq.append(now)
