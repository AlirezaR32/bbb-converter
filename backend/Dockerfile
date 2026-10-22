# syntax=docker/dockerfile:1
# FastAPI backend (also used as the base for the Celery worker image).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg/ffprobe for media processing; libcairo2 for SVG slide rasterization.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libcairo2 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# Alembic migrations run first; inline worker mode is the default single-node setup.
CMD ["sh", "-c", "alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
