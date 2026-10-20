"""Application configuration loaded from environment variables (.env supported)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ---
    app_name: str = "BigBlueButton Recording Converter"
    version: str = "1.0.0"
    debug: bool = False
    secret_key: str = "dev-insecure-secret-change-me"
    # Public URL of this backend (used to construct/allow the demo recording URL).
    backend_public_url: str = "http://127.0.0.1:8000"

    # --- database / queue ---
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'bbb_converter.db'}"
    redis_url: str = "redis://localhost:6379/0"
    job_queue: str = "inline"  # inline | celery

    # --- storage ---
    data_dir: Path = BASE_DIR / "data"
    output_ttl_hours: float = 24.0
    cleanup_interval_minutes: float = 10.0
    storage_quota_gb: float = 25.0
    min_free_disk_gb: float = 1.5

    # --- limits ---
    max_concurrent_jobs: int = 2
    max_jobs_per_ip: int = 4
    max_recording_hours: float = 8.0
    max_asset_mb: float = 2048.0
    max_total_assets_mb: float = 4096.0
    ffmpeg_timeout_s: int = 3 * 60 * 60
    download_timeout_s: int = 30 * 60
    request_timeout_s: int = 30
    rate_limit_per_minute: int = 20

    # --- network / SSRF ---
    allow_insecure_http: bool = False
    verify_tls: bool = True
    max_redirects: int = 5
    allowed_ports: str = "80,443"
    # Extra URL prefixes that bypass private-IP/port checks (used by demo mode only).
    extra_allowed_url_prefixes: str = ""

    # --- demo mode (synthetic recording, clearly separated from production) ---
    demo_mode: bool = True

    # --- cors ---
    cors_origins: str = "*"

    @field_validator("allowed_ports", "extra_allowed_url_prefixes", "cors_origins", mode="before")
    @classmethod
    def _blank_to_empty(cls, v):  # noqa: ANN001
        return v or ""

    @field_validator("database_url", mode="before")
    @classmethod
    def _valid_sqlalchemy_url(cls, v):  # noqa: ANN001
        """Ignore foreign DATABASE_URL env values (e.g. Prisma-style 'file:...')."""
        allowed = ("sqlite", "postgresql", "postgres", "mysql", "mariadb")
        if isinstance(v, str) and v.split(":", 1)[0] not in allowed:
            return f"sqlite:///{BASE_DIR / 'data' / 'bbb_converter.db'}"
        return v

    # ---- derived helpers -------------------------------------------------
    @property
    def output_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def demo_dir(self) -> Path:
        return self.data_dir / "demo"

    @property
    def allowed_port_set(self) -> set[int]:
        return {p for p in (int(x) for x in self.allowed_ports.split(",") if x.strip()) if p > 0}

    @property
    def allowed_url_prefixes(self) -> tuple[str, ...]:
        prefixes = [p.strip() for p in self.extra_allowed_url_prefixes.split(",") if p.strip()]
        if self.demo_mode:
            prefixes.append(self.demo_base_url.rstrip("/"))
        return tuple(p for p in prefixes if p)

    @property
    def demo_base_url(self) -> str:
        return self.backend_public_url.rstrip("/") + "/demo"

    @property
    def demo_recording_url(self) -> str:
        return f"{self.demo_base_url}/playback/presentation/2.3/{self.demo_recording_id}"

    @property
    def demo_recording_id(self) -> str:
        return "dem0recording0000000000000000000000000000000-1700000000000"

    @property
    def max_asset_bytes(self) -> int:
        return int(self.max_asset_mb * 1024 * 1024)

    @property
    def max_total_assets_bytes(self) -> int:
        return int(self.max_total_assets_mb * 1024 * 1024)

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.output_dir, self.work_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    # Allow env var override of data dir before first use.
    s = Settings()
    env_data = os.environ.get("DATA_DIR")
    if env_data:
        s.data_dir = Path(env_data)
    # Only honor DATABASE_URL when it is a SQLAlchemy-compatible URL (the
    # surrounding sandbox may expose a Prisma-style value we must ignore).
    env_db = os.environ.get("DATABASE_URL", "")
    if env_db and env_db.split(":", 1)[0] in {"sqlite", "postgresql", "postgres", "mysql", "mariadb"}:
        s.database_url = env_db
    s.ensure_dirs()
    return s
