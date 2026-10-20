# BigBlueButton Recording Converter

Convert publicly accessible BigBlueButton recordings into **real, downloadable video files** —
MP4 (H.264/AAC), WebM (VP9/Opus), or MP3 — with presentation slides, whiteboard annotations,
webcam picture-in-picture, and synchronized audio rebuilt by an FFmpeg pipeline.

> This is **not** an HTML-renamer. If a recording has no video, the converter inspects the
> playback bundle, downloads the underlying media assets, and *reconstructs* a video. If the
> server does not expose the required media, it reports exactly why instead of pretending.

---

## Table of Contents

1. [What it does](#what-it-does)
2. [Architecture](#architecture)
3. [Quick start (development)](#quick-start-development)
4. [Docker deployment](#docker-deployment)
5. [API reference](#api-reference)
6. [BigBlueButton compatibility](#bigbluebutton-compatibility)
7. [Security model](#security-model)
8. [Performance & reliability](#performance--reliability)
9. [Demo mode](#demo-mode)
10. [Testing](#testing)
11. [Configuration reference](#configuration-reference)
12. [Troubleshooting](#troubleshooting)

---

## What it does

```
Paste URL ──► Validate+SSRF guard ──► Inspect assets ──► Pick strategy ──► Convert (FFmpeg)
                                                                            │
   MP4 / WebM / MP3 ◄── signed download link ◄── progress via SSE ◄─────────┘
```

1. **Validate** the playback URL (`/playback/presentation/2.3/<record-id>`) and resolve every
   DNS address to public IP space (SSRF protection).
2. **Inspect** what the server actually exposes: `metadata.xml`, slide timeline
   (`shapes.svg` / `slides_new.xml`), audio (`audio/audio.webm`, legacy `audio_only.*`),
   webcam (`video/webcams.webm`, legacy `webcam.webm`), screenshare, or a ready-made video.
   Probes validate **content types**, because many BBB servers answer HTTP 200 with the SPA
   `index.html` for every missing file (soft-404).
3. **Choose a strategy** and show it to the user *before* converting:
   | Strategy | When | Output |
   |---|---|---|
   | `direct` | a complete video is published | remux (stream copy) or transcode |
   | `reconstruct` | slides + webcam/audio exist | 1600×900 canvas: slides by timeline, webcam PiP, synchronized audio |
   | `streams` | webcam/screenshare + audio only | merge + pad to equal length |
   | `audio_only` | only audio published | MP3, or MP4 with a title card |
   | `unsupported` | nothing usable | honest error + explanation |
4. **Convert** in a background worker with real progress: download bytes, per-slide rendering,
   and FFmpeg `out_time` streamed to the UI over Server-Sent Events.
5. **Deliver** through an HMAC-signed, expiring download link. Artifacts expire automatically.

### Fidelity notes (honest limitations)

- Slide **pan/zoom** (`panzooms.xml`) and the **live cursor** are not animated — each slide is
  shown fitted to the canvas for its full interval.
- Whiteboard annotations are composited **per slide interval** (annotation-level timing is
  approximated).
- Chat messages are not rendered into the video.
- The webcam PiP is a fixed 400×300 box in the bottom-right corner.

These limitations are reported in the API (`strategy.limitations`), shown in the UI, and
stored on the job (`fidelity_notes`).

---

## Architecture

```
┌────────────────────┐        ┌─────────────────────────────┐
│  Next.js 16 (UI)   │  HTTP  │  FastAPI backend            │
│  React 19 + TS     │───────►│  /api/recordings/analyze    │
│  Tailwind 4       │ (proxy)│  /api/conversions[...]      │
│  SSE progress      │◄──SSE──│  /api/health                │
└────────────────────┘        │  SSRF guard · rate limits   │
                              └──────────┬──────────────────┘
                                         │ submit job
                       ┌─────────────────┼──────────────────┐
                       ▼ inline (default)│                  ▼ celery (profile "queue")
              ┌──────────────────┐       │        ┌──────────────┐
              │ ThreadPool worker│       │        │ Celery worker│
              │ (FastAPI process)│       │        │ + beat       │
              └────────┬─────────┘       │        └──────┬───────┘
                       │                 │               │
                       ▼                 ▼               ▼
              ┌───────────────────────────────────────────────┐
              │  Pipeline: SafeFetcher → ffprobe → FFmpeg     │
              │  (cairosvg slide rasterization + compositing) │
              └────────────────────┬──────────────────────────┘
                                   ▼
                     SQLite (dev) / PostgreSQL (prod)
                     outputs/ + work/ with TTL cleanup
```

- **Frontend** — `src/` (Next.js App Router, TypeScript, Tailwind 4, shadcn/ui, framer-motion).
  The dev server and the production image proxy `/api/*` to the backend (no CORS needed,
  SSE passes through).
- **Backend** — `backend/app/` (FastAPI, SQLAlchemy 2, pydantic-settings).
  - `security/` — URL guard + SSRF protection, redirect-validating fetcher, signed tokens, rate limiter
  - `bbb/` — recording inspector + parsers (metadata.xml, shapes.svg, slides_new.xml)
  - `media/` — FFmpeg runner (real progress, timeouts, cancellation) and the strategy pipeline
  - `jobs/` — store, inline ThreadPool executor, Celery app/tasks, TTL cleanup
  - `demo/` — synthetic recording generator (demo mode)
- **Migrations** — Alembic (`backend/alembic/`), auto-applied on container start.

---

## Quick start (development)

Requirements: **Python 3.11+**, **FFmpeg + ffprobe**, **Node 20+/Bun**, and the Python packages
from `backend/requirements.txt` (the `cairosvg` package needs the system `libcairo2`).

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
cp ../.env.example .env               # optional; sane defaults are built in
python -m uvicorn app.main:app --port 8000
#    -> http://127.0.0.1:8000/api/health

# 2. Frontend (separate shell, from the repo root)
bun install                           # or: npm install
bun run dev                           # or: npm run dev
#    -> http://localhost:3000  (proxies /api/* to :8000)
```

Open `http://localhost:3000`, paste a playback URL (or click **Try the bundled demo
recording**), analyze, choose a format, convert.

The frontend expects the backend on `http://127.0.0.1:8000` (override with `BACKEND_ORIGIN`
in `next.config.ts` / environment).

---

## Docker deployment

```bash
# Single node (inline queue + PostgreSQL, no Redis needed):
docker compose up --build
# -> UI on http://localhost:3000

# Production queue mode (Celery worker + beat + Redis):
JOB_QUEUE=celery docker compose --profile queue up --build

# Scale conversions:
CELERY_CONCURRENCY=4 JOB_QUEUE=celery docker compose --profile queue up --build
```

Services: `frontend` (Next standalone), `backend` (uvicorn + Alembic autoupgrade),
`worker`/`beat`/`redis` (queue profile), `postgres`. Output artifacts live in the shared
`media_data` volume; the backend serves downloads, the worker writes outputs.

Copy `.env.example` and set at minimum **`SECRET_KEY`** (downloads are signed with it) and
**`BACKEND_PUBLIC_URL`** (used for the demo URL allow-list).

For a reverse proxy in front of the frontend, disable response buffering for SSE
(`X-Accel-Buffering: no` is already sent by the API; e.g. in nginx:
`proxy_buffering off` for `/api/conversions/*/events`).

---

## API reference

All endpoints return structured JSON. Errors use
`{"error": {"code": "...", "message": "...", "details": {...}}}`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/recordings/analyze` | Validate + inspect a recording URL → assets, strategy, estimates |
| `POST` | `/api/conversions` | Create a conversion job (`202`, body: `{url, format, include_webcam_pip}`) |
| `GET` | `/api/conversions` | List recent jobs |
| `GET` | `/api/conversions/{id}` | Job status/progress (+ signed download URL when complete) |
| `GET` | `/api/conversions/{id}/events` | **SSE** progress stream (`progress`/`end` events) |
| `GET` | `/api/conversions/{id}/download?token=` | Stream the output file (signed, expiring token) |
| `DELETE` | `/api/conversions/{id}` | Cancel (if running) and delete job + artifacts |
| `GET` | `/api/health` | Liveness, FFmpeg availability, queue mode, storage |

Example:

```bash
curl -s http://localhost:8000/api/recordings/analyze \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://bbb.example.edu/playback/presentation/2.3/<id>"}' | jq .strategy

curl -s http://localhost:8000/api/conversions -H 'Content-Type: application/json' \
  -d '{"url":"https://bbb.example.edu/playback/presentation/2.3/<id>","format":"mp4"}'
```

Error codes (non-exhaustive): `INVALID_URL`, `UNSUPPORTED_PLAYBACK_VERSION`, `SSRF_BLOCKED`,
`SOURCE_UNREACHABLE`, `SOURCE_TIMEOUT`, `SOURCE_FORBIDDEN`, `ASSETS_MISSING`,
`UNSUPPORTED_RECORDING`, `RECORDING_TOO_LONG`, `CONCURRENCY_LIMIT`, `QUOTA_EXCEEDED`,
`RATE_LIMITED`, `FFMPEG_FAILED`, `CANCELED`, `INVALID_TOKEN`, `TOKEN_EXPIRED`.

---

## BigBlueButton compatibility

| BBB version | Playback path | Notes |
|---|---|---|
| 2.0 | `/playback/presentation/2.0/<id>` | audio `audio/audio.ogg`, webcam `video/webcam.webm` |
| 2.3 – 3.x | `/playback/presentation/2.3/<id>` | audio `audio/audio.webm` (2.3: `audio_only.*`), webcam `video/webcams.webm` (audio usually embedded), slides via `shapes.svg` (tldraw-era SVG) or `slides_new.xml` |

Real-world quirks this converter handles:

- **SPA soft-404 servers** — some origins return the playback `index.html` (HTTP 200) for
  *every* asset under the playback path. The inspector detects this by content type and
  automatically probes the canonical published tree at `/presentation/<id>/...` instead.
- **BBB 3.x media naming** — `video/webcams.webm` + embedded audio, `audio/audio.webm`.
- **tldraw slide SVGs** — rasterized with cairosvg; classic PNG slide decks are used directly.
- **Duration mismatches** — metadata `start/end` can exceed the published media; the pipeline
  caps output at the probed media duration (no endless frozen tail).
- If the server does not expose the media at all (auth-protected or unpublished), the API
  fails with `ASSETS_MISSING` and a precise explanation — never a fake download.

Not supported: recordings behind authentication/cookies (by design — the tool only fetches
publicly accessible assets), the `screenshare`-only/`video` playback formats other than
`presentation`, and locked-down servers that block direct media retrieval.

---

## Security model

- **SSRF protection** — HTTPS enforced by default (`ALLOW_INSECURE_HTTP` to relax in dev);
  only ports 80/443; every resolved IP must be public (loopback / private / link-local /
  reserved / multicast / cloud-metadata endpoints are rejected); every **redirect hop** is
  re-validated; path restricted to BBB playback shapes; URL credentials/query/fragments
  rejected. A single-host allow-list (`EXTRA_ALLOWED_URL_PREFIXES`) exists for the demo.
- **Signed downloads** — HMAC-SHA256 tokens bound to job id + expiry (`SECRET_KEY`); the
  stream endpoint re-checks job state and file existence.
- **Abuse limits** — per-IP sliding-window rate limiting, per-IP and global concurrency
  caps, storage quota, minimum free disk space, per-asset and total download caps,
  maximum recording duration, FFmpeg wall-clock timeout (process-group kill).
- **Hygiene** — unpredictable job ids (uuid4 hex), isolated per-job work directories,
  TTL-based cleanup of outputs and temp files, no credentials/stack traces leaked in
  responses, operational logs never store full user URLs.
- The tool never bypasses authentication or recording permissions, and does not use browser
  capture to exfiltrate protected content.

## Performance & reliability

- Conversions run in background workers (inline ThreadPool by default, Celery in production).
- Downloads stream to disk in 256 KB chunks — no in-memory buffering of large assets.
- FFmpeg subprocesses run with `start_new_session`, `-progress pipe:1` (real progress),
  timeouts, and cancellation polling between stages and inside encode loops.
- Stream copy is preferred whenever the source codecs already match the target container
  (e.g. VP9/Vorbis → WebM remux is instant).
- Expired outputs are purged automatically (inline loop or Celery beat); jobs stuck in
  `running` after a worker crash are failed by a watchdog.

---

## Demo mode

`DEMO_MODE=true` (default in dev) generates a **synthetic** recording bundle at startup
(FFmpeg tone/test-pattern media + 3 SVG slides + metadata) served under `/demo/**` on the
backend. Its URL is whitelisted explicitly and clearly separated from production input.
Use it to exercise the full pipeline offline: analyze → reconstruct MP4 → download.

Disable with `DEMO_MODE=false` in production.

## Testing

```bash
cd backend
python -m pytest tests/ -q
```

36 tests, fully offline: URL validation + SSRF (literal IPs, private ranges, metadata
endpoints, ports, versions), fetcher redirect/size-cap behaviour, inspection against a local
fake BBB origin, MP4/WebM/MP3 conversion flows (real FFmpeg on the synthetic recording),
SSE stream, signed-token security, rate limits, concurrency limits, and the slide renderer.

End-to-end smoke script (expects the backend on `:8000`):

```bash
bash scripts/smoke_demo.sh mp4    # also: webm, mp3
```

## Configuration reference

See [.env.example](.env.example) for the full annotated list. Highlights:

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | dev placeholder | HMAC key for download tokens — **change in production** |
| `DATABASE_URL` | SQLite | `postgresql+psycopg2://user:pass@host/db` in production |
| `JOB_QUEUE` | `inline` | `celery` enables the Redis-backed worker |
| `MAX_CONCURRENT_JOBS` | 2 | global conversion parallelism |
| `MAX_RECORDING_HOURS` | 8 | refuses longer recordings |
| `MAX_ASSET_MB` / `MAX_TOTAL_ASSETS_MB` | 2048 / 4096 | per-asset / total download caps |
| `OUTPUT_TTL_HOURS` | 24 | output lifetime before automatic deletion |
| `STORAGE_QUOTA_GB` / `MIN_FREE_DISK_GB` | 25 / 2 | storage guards |
| `VERIFY_TLS` | true | set `false` only for self-signed test servers |
| `DEMO_MODE` | true (dev) | serves the synthetic demo recording |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `API offline` badge in the UI | Backend not running / `BACKEND_ORIGIN` mismatch. Check `http://127.0.0.1:8000/api/health`. |
| `Cannot resolve host` | DNS issue on the server running the converter. |
| `TLS_ERROR` with self-hosted BBB | Set `VERIFY_TLS=false` **only** if you trust the network, or install the CA. |
| `ASSETS_MISSING` on a recording that plays in the browser | The server restricts direct media access or the recording is unpublished — nothing can be downloaded honestly. |
| Progress stuck at 0% | Source is very slow; check backend logs. Downloads have a 30 min cap. |
| SSE shows nothing (proxy) | Ensure the reverse proxy does not buffer event streams (see Deployment). |
| `cairosvg` install failure | System package `libcairo2` is required (`apt-get install libcairo2`). |
| Jobs stuck `running` forever | Watchdog fails them after 4 h; or `DELETE /api/conversions/{id}`. |
