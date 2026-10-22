"""Database models: conversion jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_job_id() -> str:
    return uuid.uuid4().hex


class ConversionJob(Base):
    __tablename__ = "conversion_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_job_id)
    source_url: Mapped[str] = mapped_column(Text)
    server_host: Mapped[str] = mapped_column(String(255), default="")
    meeting_id: Mapped[str] = mapped_column(String(255), default="")
    playback_version: Mapped[str] = mapped_column(String(16), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    format: Mapped[str] = mapped_column(String(8), default="mp4")  # mp4 | webm | mp3
    strategy: Mapped[str] = mapped_column(String(24), default="")  # direct | streams | reconstruct | audio_only
    include_webcam_pip: Mapped[bool] = mapped_column(Boolean, default=True)
    # Snapshot of the recording inspection (assets, capabilities, notes).
    assets_json: Mapped[dict] = mapped_column(JSON, default=dict)
    fidelity_notes: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # queued | running | completed | failed | canceled | expired
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    # queued | downloading | probing | rendering | encoding | finalizing | done
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_detail: Mapped[str] = mapped_column(Text, default="")

    error_code: Mapped[str] = mapped_column(String(48), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")

    output_filename: Mapped[str] = mapped_column(String(255), default="")
    output_size: Mapped[int] = mapped_column(Integer, default=0)
    output_duration: Mapped[float] = mapped_column(Float, default=0.0)

    client_ip: Mapped[str] = mapped_column(String(64), default="")
    canceled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    TERMINAL_STATUSES = ("completed", "failed", "canceled", "expired")
    ACTIVE_STATUSES = ("queued", "running")

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_url": self.source_url,
            "server_host": self.server_host,
            "meeting_id": self.meeting_id,
            "playback_version": self.playback_version,
            "title": self.title,
            "duration_seconds": self.duration_seconds,
            "format": self.format,
            "strategy": self.strategy,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 4),
            "progress_detail": self.progress_detail,
            "fidelity_notes": self.fidelity_notes or [],
            "error": (
                {"code": self.error_code, "message": self.error_message}
                if self.error_code else None
            ),
            "output": (
                {
                    "filename": self.output_filename,
                    "size_bytes": self.output_size,
                    "duration_seconds": self.output_duration,
                    "format": self.format,
                }
                if self.status == "completed" else None
            ),
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "finished_at": self.finished_at.isoformat() + "Z" if self.finished_at else None,
            "expires_at": self.expires_at.isoformat() + "Z" if self.expires_at else None,
        }
