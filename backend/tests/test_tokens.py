"""Signed download tokens + rate limiter tests."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.errors import JobError
from app.security.tokens import RateLimiter, sign_download_token, verify_download_token


def test_token_roundtrip():
    s = get_settings()
    token, exp = sign_download_token(s, "job123", ttl_seconds=60)
    verify_download_token(s, "job123", token)  # must not raise


def test_token_tamper_rejected():
    s = get_settings()
    token, _ = sign_download_token(s, "job123", ttl_seconds=60)
    with pytest.raises(JobError) as e:
        verify_download_token(s, "other-job", token)
    assert e.value.code == "INVALID_TOKEN"


def test_token_expiry_rejected():
    s = get_settings()
    token, _ = sign_download_token(s, "job123", ttl_seconds=-10)
    with pytest.raises(JobError) as e:
        verify_download_token(s, "job123", token)
    assert e.value.code == "TOKEN_EXPIRED"


def test_token_malformed_rejected():
    with pytest.raises(JobError):
        verify_download_token(get_settings(), "job123", "garbage")


def test_rate_limiter():
    limiter = RateLimiter(per_minute=3)
    for _ in range(3):
        limiter.check("ip1")
    with pytest.raises(JobError) as e:
        limiter.check("ip1")
    assert e.value.code == "RATE_LIMITED"
    limiter.check("ip2")  # independent buckets
