"""SafeFetcher security behaviour (redirects, caps) using local HTTP servers."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.config import get_settings
from app.errors import SourceError
from app.security.fetcher import SafeFetcher, soft404
from app.security.url_guard import validate_recording_url


@pytest.fixture(scope="module")
def evil_server():
    """A tiny origin that redirects to private addresses and serves HTML fake-404s."""
    state = {"mode": "html"}

    class H(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._respond(head=True)

        def do_GET(self):
            self._respond(head=False)

        def _respond(self, head):
            if self.path.startswith("/redirect-private"):
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                self.end_headers()
                return
            if self.path.startswith("/redirect-loop"):
                self.send_response(302)
                self.send_header("Location", self.path)
                self.end_headers()
                return
            if state["mode"] == "html":
                body = b"<html><body>spa fallback</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)
            else:
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)

        def log_message(self, *a):  # silence
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 8766), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:8766", state
    httpd.shutdown()


def test_soft404_detection():
    assert soft404("text/html", ("text/xml",)) is True
    assert soft404("text/xml; charset=utf-8", ("text/xml",)) is False
    assert soft404("video/webm", ("video/", "audio/")) is False
    assert soft404("", ("video/",)) is False


def test_redirect_to_private_blocked(evil_server):
    base, _ = evil_server
    settings = get_settings()
    fetcher = SafeFetcher(settings)
    try:
        # Direct private URL is blocked by the URL guard before any request.
        from app.errors import UrlValidationError

        with pytest.raises(UrlValidationError):
            validate_recording_url("http://169.254.169.254/x", settings)
        # Redirect hop to private IP is blocked by the fetcher.
        with pytest.raises(SourceError) as e:
            fetcher.fetch(f"{base}/redirect-private")
        assert e.value.code == "SSRF_BLOCKED"
    finally:
        fetcher.close()


def test_redirect_loop_blocked(evil_server):
    base, _ = evil_server
    fetcher = SafeFetcher(get_settings())
    try:
        with pytest.raises(SourceError):
            fetcher.fetch(f"{base}/redirect-loop")
    finally:
        fetcher.close()


def test_size_cap(evil_server):
    base, state = evil_server
    state["mode"] = "plain"
    fetcher = SafeFetcher(get_settings())
    try:
        with pytest.raises(SourceError) as e:
            fetcher.fetch(f"{base}/small", max_bytes=1)
        assert "exceeded" in e.value.message or "too large" in e.value.message
    finally:
        fetcher.close()
        state["mode"] = "html"
