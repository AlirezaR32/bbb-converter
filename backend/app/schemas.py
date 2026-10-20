"""Pydantic schemas for API requests/responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class AssetInfo(BaseModel):
    available: bool
    url: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    note: str | None = None


class SlidesInfo(BaseModel):
    available: bool
    count: int = 0
    format: str | None = None  # svg | png | unknown
    note: str | None = None


class StrategyInfo(BaseModel):
    id: Literal["direct", "streams", "reconstruct", "audio_only", "unsupported"]
    label: str
    supported: bool
    explanation: str
    limitations: list[str] = []


class RecordingInfoOut(BaseModel):
    valid: bool = True
    url: str
    server_host: str
    meeting_id: str
    playback_version: str
    title: str = ""
    duration_seconds: float = 0.0
    participants: int | None = None
    start_time: str | None = None
    assets: dict[str, Any]
    slides: SlidesInfo
    strategy: StrategyInfo
    estimated_output_mb: dict[str, float] = {}
    warnings: list[str] = []


class CreateJobRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    format: Literal["mp4", "webm", "mp3"] = "mp4"
    include_webcam_pip: bool = True


class JobOut(BaseModel):
    id: str
    status: str
    stage: str
    progress: float
    progress_detail: str = ""
    format: str
    strategy: str = ""
    title: str = ""
    source_url: str = ""
    duration_seconds: float = 0.0
    fidelity_notes: list[str] = []
    error: dict | None = None
    output: dict | None = None
    download: dict | None = None
    created_at: str | None = None
    finished_at: str | None = None
    expires_at: str | None = None


class JobListOut(BaseModel):
    jobs: list[JobOut]


class HealthOut(BaseModel):
    status: str
    version: str
    ffmpeg_available: bool
    ffmpeg_version: str | None = None
    queue_mode: str
    active_jobs: int
    storage_free_gb: float
    demo_mode: bool
    demo_url: str | None = None
    limits: dict[str, Any]
