# Deploying to Render (API) + Vercel (UI)

Split the app across the two platforms:

```
┌──────────────┐   /api/* proxy (build-time rewrite)   ┌────────────────────────┐
│   Vercel     │ ────────────────────────────────────► │        Render          │
│  Next.js UI  │                                       │  FastAPI + FFmpeg API  │
│ (SSR/static) │ ◄── SSE + polling progress ────────── │   + PostgreSQL + disk  │
└──────────────┘                                       └────────────────────────┘
        ▲                                                      ▲
        └────────── downloads stream DIRECT from Render ───────┘
                   (PUBLIC_DOWNLOAD_BASE_URL, signed links)
```

- **Render** runs the heavy work: FFmpeg pipelines, asset downloads, storage, PostgreSQL.
- **Vercel** serves the UI and proxies `/api/*` to Render (same-origin, no CORS setup).
- **Downloads never pass through Vercel** — completed links are absolute Render URLs signed
  with HMAC tokens, so multi-hundred-MB files bypass serverless function limits.

---

## 1. Push the repo to GitHub/GitLab

Both platforms deploy from a Git repo. Push this project (the `render.yaml` at the root is
the Render blueprint; the repo root is also the Next.js app Vercel detects).

## 2. Deploy the API on Render

**Option A — Blueprint (recommended, one click):**
1. Render dashboard → **New → Blueprint** → select the repo.
2. Render reads `render.yaml` and creates: web service `bbb-converter-api` (Docker,
   health check `/api/health`) + PostgreSQL `bbb-converter-db`. `SECRET_KEY` is generated
   automatically; it prompts for `BACKEND_PUBLIC_URL` / `PUBLIC_DOWNLOAD_BASE_URL`.
3. When the first deploy is live, note the service URL (e.g.
   `https://bbb-converter-api.onrender.com`), then set **both** env vars to it
   (Service → Environment):
   - `BACKEND_PUBLIC_URL=https://bbb-converter-api.onrender.com`
   - `PUBLIC_DOWNLOAD_BASE_URL=https://bbb-converter-api.onrender.com`
   Render redeploys automatically. Verify: `curl https://.../api/health` →
   `{"status":"ok","ffmpeg":"7.x",...}`.

**Option B — Manual:** New → **Web Service** → runtime **Docker** → root directory
**leave blank**, Docker context `./backend`, Dockerfile `./backend/Dockerfile` → add the
env vars from the table below → Create. Also create a **PostgreSQL** instance and copy its
*Internal Database URL* into `DATABASE_URL`.

Environment variables (backend):

| Variable | Value | Why |
|---|---|---|
| `DATABASE_URL` | *(from database — auto with Blueprint)* | job metadata in Postgres |
| `SECRET_KEY` | generated / long random hex | signs download tokens |
| `BACKEND_PUBLIC_URL` | `https://<service>.onrender.com` | demo-recording URL + allow-list |
| `PUBLIC_DOWNLOAD_BASE_URL` | `https://<service>.onrender.com` | absolute download links |
| `CORS_ORIGINS` | `*` | direct downloads from the Vercel domain |
| `DEMO_MODE` | `true` (production: `false`) | bundled test recording |
| `JOB_QUEUE` | `inline` (or `celery`, see below) | single-node queue, no Redis needed |
| `OUTPUT_TTL_HOURS` | `24` | auto-delete finished outputs |
| `MAX_CONCURRENT_JOBS` | `1` on 512 MB plans | FFmpeg needs headroom |

The backend Docker image already contains **FFmpeg + libcairo** and runs
`alembic upgrade head` (DB migrations) before serving — no extra setup.

**Celery mode (optional):** uncomment the `worker` + `keyvalue` (Redis) blocks in
`render.yaml`, set `JOB_QUEUE=celery` on the web service, and redeploy the blueprint.

## 3. Deploy the UI on Vercel

1. Vercel → **Add New → Project** → import the same repo.
2. Framework preset auto-detects **Next.js**. Keep the root directory as the repo root.
3. Add one build-time environment variable:
   - `BACKEND_ORIGIN=https://bbb-converter-api.onrender.com` (your Render URL)
4. Deploy. Vercel builds the standalone Next app; `next.config.ts` wires the rewrite
   `/api/:path* → $BACKEND_ORIGIN/api/:path*`, so the UI talks to Render same-origin.

## 4. Test the deployment

1. Open `https://<your-app>.vercel.app`.
2. Click **Try the bundled demo recording** → **Analyze** → pick MP4 → **Convert**.
   A real end-to-end conversion proves FFmpeg, storage, the queue, and downloads.
3. Then paste a real BigBlueButton playback URL and convert.

---

## Plans, limits & how this design copes

| Constraint | Behaviour |
|---|---|
| Render **free** spins down after 15 min idle | First request after idle waits ~50 s (cold start). Downloads of finished files fail with *410 expired* after a spin-down/redeploy — the free tier's disk is ephemeral. |
| Render free = 512 MB RAM | Fine for the demo recording and short clips. Long real recordings: use **Standard (2 GB)** and keep `MAX_CONCURRENT_JOBS=1`. |
| Render free Postgres **expires after 30 days** | Switch the database to `basic-256mb`+ for anything permanent. |
| Render paid plans can attach a **persistent disk** | Add a disk at `/app/data` (see the commented block in `render.yaml`) so outputs survive deploys; the TTL cleaner still prunes them. |
| Vercel functions limit SSE duration | The UI starts a **2 s polling loop** that automatically takes over when the SSE stream is cut — progress tracking works regardless. |
| Vercel function response limits | Irrelevant by design: `PUBLIC_DOWNLOAD_BASE_URL` makes download buttons link **directly to Render**, never through Vercel. |

## Updating

Push to the default branch → both platforms rebuild automatically (Vercel from the Git
integration; Render from Auto-Deploy). Migrations run on every backend boot.

## Troubleshooting

- **UI loads but "Analyzer unreachable"** → `BACKEND_ORIGIN` on Vercel is wrong or the
  Render service is mid-deploy; check `curl https://<render>/api/health`.
- **Demo chip fills the wrong URL** → `BACKEND_PUBLIC_URL` on Render must be the public
  `https://…onrender.com` URL, not an internal hostname.
- **Download gives 410 after a while on the free plan** → the service spun down and the
  ephemeral disk was reset; convert again, or move to a paid plan with a disk.
- **Conversion killed mid-way** → out of memory (512 MB plan); raise the plan or convert
  shorter recordings / MP3 only.
- **Progress jumps in 2 s steps** → SSE is being buffered by the proxy and the UI switched
  to polling; harmless, the result is identical.
