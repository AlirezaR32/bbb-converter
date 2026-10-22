"""API flow tests: analyze, job creation, progress, download, delete, SSE."""

from __future__ import annotations

import time

import pytest


def _demo_url(client):
    h = client.get("/api/health").json()
    assert h["status"] in ("ok", "degraded")
    assert h["demo_mode"] is True
    return h["demo_url"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["ffmpeg_available"] is True
    assert "limits" in d


def test_analyze_rejects_invalid_url(client):
    r = client.post("/api/recordings/analyze", json={"url": "not-a-url"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] in ("INVALID_URL",)


def test_analyze_blocks_ssrf(client):
    r = client.post("/api/recordings/analyze",
                    json={"url": "https://169.254.169.254/playback/presentation/2.3/abcdefgh12345678"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "SSRF_BLOCKED"


def test_analyze_demo(client, demo_server):
    url = _demo_url(client).replace(":8000", ":8765")
    r = client.post("/api/recordings/analyze", json={"url": url})
    assert r.status_code == 200
    d = r.json()
    assert d["valid"] is True
    assert d["strategy"]["id"] == "reconstruct"
    assert d["assets"]["webcam"]["available"] is True
    assert d["duration_seconds"] == 66.0


@pytest.mark.parametrize("fmt,codec_a,codec_v", [
    ("mp4", "aac", "h264"),
    ("webm", "opus", "vp9"),
])
def test_conversion_flow(client, demo_server, fmt, codec_a, codec_v):
    url = _demo_url(client).replace(":8000", ":8765")
    r = client.post("/api/conversions", json={"url": url, "format": fmt})
    assert r.status_code == 202, r.text
    job = r.json()
    jid = job["id"]

    # poll until terminal (max 120 s)
    final = None
    for _ in range(60):
        time.sleep(2)
        final = client.get(f"/api/conversions/{jid}").json()
        if final["status"] in ("completed", "failed", "canceled"):
            break
    assert final is not None and final["status"] == "completed", final
    assert final["output"]["format"] == fmt
    assert final["output"]["size_bytes"] > 10_000
    assert final["download"]["token"]

    # download with token
    dl = final["download"]["url"]
    path = dl if dl.startswith("http") else f"http://testserver{dl}"
    resp = client.get(f"/api/conversions/{jid}/download?token={final['download']['token']}")
    assert resp.status_code == 200
    assert len(resp.content) > 10_000

    # download without token is rejected
    resp2 = client.get(f"/api/conversions/{jid}/download")
    assert resp2.status_code == 403

    # delete removes the job
    r = client.delete(f"/api/conversions/{jid}")
    assert r.status_code == 200
    assert client.get(f"/api/conversions/{jid}").status_code == 404


def test_mp3_flow(client, demo_server):
    url = _demo_url(client).replace(":8000", ":8765")
    r = client.post("/api/conversions", json={"url": url, "format": "mp3"})
    jid = r.json()["id"]
    final = None
    for _ in range(45):
        time.sleep(2)
        final = client.get(f"/api/conversions/{jid}").json()
        if final["status"] in ("completed", "failed", "canceled"):
            break
    assert final["status"] == "completed", final
    client.delete(f"/api/conversions/{jid}")


def test_absolute_download_url(client, demo_server, monkeypatch):
    """PUBLIC_DOWNLOAD_BASE_URL must produce absolute (cross-origin) download links."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_download_base_url", "https://bbb-api.example.com")
    url = _demo_url(client).replace(":8000", ":8765")
    jid = client.post("/api/conversions", json={"url": url, "format": "mp3"}).json()["id"]
    final = None
    for _ in range(45):
        time.sleep(2)
        final = client.get(f"/api/conversions/{jid}").json()
        if final["status"] in ("completed", "failed", "canceled"):
            break
    assert final["status"] == "completed", final
    assert final["download"]["url"].startswith("https://bbb-api.example.com/api/conversions/")
    # The direct link itself must work (token signed for the same job).
    assert client.get(final["download"]["url"].replace("https://bbb-api.example.com", "")).status_code == 200
    client.delete(f"/api/conversions/{jid}")


def test_sse_stream_reports_progress(client, demo_server):
    url = _demo_url(client).replace(":8000", ":8765")
    jid = client.post("/api/conversions", json={"url": url, "format": "mp3"}).json()["id"]
    with client.stream("GET", f"/api/conversions/{jid}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = []
        for line in resp.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if "end" in events:
                break
            if len(events) > 200:
                break
    assert "progress" in events
    client.delete(f"/api/conversions/{jid}")


def test_job_not_found(client):
    assert client.get("/api/conversions/deadbeef").status_code == 404


def test_concurrency_limit(client, demo_server):
    """More active jobs than the limit -> 429 CONCURRENCY_LIMIT."""
    url = _demo_url(client).replace(":8000", ":8765")
    ids = []
    try:
        for _ in range(2):
            r = client.post("/api/conversions", json={"url": url, "format": "mp4"})
            ids.append(r.json()["id"])
        r = client.post("/api/conversions", json={"url": url, "format": "mp4"})
        # max_concurrent_jobs=2 in test env
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "CONCURRENCY_LIMIT"
    finally:
        for jid in ids:
            client.delete(f"/api/conversions/{jid}")
