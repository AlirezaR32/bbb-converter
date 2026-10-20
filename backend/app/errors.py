"""Structured error codes shared by the API and the processing pipeline."""

from __future__ import annotations

from typing import Any

# Error codes returned in structured JSON responses.
INVALID_URL = "INVALID_URL"
UNSUPPORTED_PLAYBACK_VERSION = "UNSUPPORTED_PLAYBACK_VERSION"
SSRF_BLOCKED = "SSRF_BLOCKED"
SOURCE_UNREACHABLE = "SOURCE_UNREACHABLE"
SOURCE_TIMEOUT = "SOURCE_TIMEOUT"
SOURCE_FORBIDDEN = "SOURCE_FORBIDDEN"
TLS_ERROR = "TLS_ERROR"
SOURCE_ERROR = "SOURCE_ERROR"
ASSETS_MISSING = "ASSETS_MISSING"
UNSUPPORTED_RECORDING = "UNSUPPORTED_RECORDING"
RECORDING_TOO_LONG = "RECORDING_TOO_LONG"
RATE_LIMITED = "RATE_LIMITED"
CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
JOB_NOT_FOUND = "JOB_NOT_FOUND"
JOB_NOT_COMPLETED = "JOB_NOT_COMPLETED"
INVALID_TOKEN = "INVALID_TOKEN"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
CANCELED = "CANCELED"
FFMPEG_FAILED = "FFMPEG_FAILED"
RENDER_FAILED = "RENDER_FAILED"
STORAGE_ERROR = "STORAGE_ERROR"
DOWNLOAD_TOO_LARGE = "DOWNLOAD_TOO_LARGE"
INTERNAL_ERROR = "INTERNAL_ERROR"

# Codes that originate inside the processing pipeline and are recorded on the
# job (no need to re-raise to the worker).
PROCESSING_CODES = {
    FFMPEG_FAILED,
    RENDER_FAILED,
    ASSETS_MISSING,
    UNSUPPORTED_RECORDING,
    QUOTA_EXCEEDED,
    CANCELED,
    "DOWNLOAD_TOO_LARGE",
    "JOB_NOT_FOUND",
    SOURCE_ERROR,
}


class AppError(Exception):
    """Base error carrying a machine-readable code + human explanation."""

    def __init__(self, code: str, message: str, http_status: int = 400,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


class UrlValidationError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        status = 403 if code == SSRF_BLOCKED else 400
        super().__init__(code, message, http_status=status, details=details)


class SourceError(AppError):
    """Errors while talking to the remote BigBlueButton server."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        status = {
            SOURCE_TIMEOUT: 504,
            SOURCE_FORBIDDEN: 502,
            TLS_ERROR: 502,
            SSRF_BLOCKED: 403,
        }.get(code, 502)
        super().__init__(code, message, http_status=status, details=details)


class ProcessingError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, http_status=500, details=details)


class JobError(AppError):
    def __init__(self, code: str, message: str, http_status: int = 404) -> None:
        super().__init__(code, message, http_status=http_status)
