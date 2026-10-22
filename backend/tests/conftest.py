"""Shared pytest fixtures. Tests run fully offline (local demo server + canned responses)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Configure environment BEFORE importing the app.
_TMP = tempfile.mkdtemp(prefix="bbb-test-")
os.environ["DATA_DIR"] = _TMP
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DEMO_MODE"] = "true"
os.environ["ALLOW_INSECURE_HTTP"] = "false"
os.environ["MAX_CONCURRENT_JOBS"] = "2"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["JOB_QUEUE"] = "inline"
# The demo allow-list must match the local test origin port (8765).
os.environ["BACKEND_PUBLIC_URL"] = "http://127.0.0.1:8765"


@pytest.fixture(scope="session")
def demo_server():
    """Run a local HTTP server that mimics a BBB origin (serves the demo bundle).

    Files live in `settings.demo_dir`; the handler strips a leading /demo so the
    URL shape matches production (http://host:8765/demo/playback/presentation/...).
    """
    from app.config import get_settings
    from app.demo.fixtures import ensure_demo_recording

    settings = get_settings()
    ensure_demo_recording(settings)

    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class DemoHandler(SimpleHTTPRequestHandler):
        def translate_path(self, path: str) -> str:
            if path.startswith("/demo/"):
                path = path[len("/demo"):]
            elif path == "/demo":
                path = "/"
            return super().translate_path(path)

        def log_message(self, *a):  # silence test output
            pass

    handler = partial(DemoHandler, directory=str(settings.demo_dir))
    httpd = ThreadingHTTPServer(("127.0.0.1", 8765), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:8765"
    httpd.shutdown()


@pytest.fixture(scope="session")
def demo_urls(demo_server):
    base = f"{demo_server}/playback/presentation/2.3/dem0recording0000000000000000000000000000000-1700000000000"
    return {"playback": base, "server": demo_server}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
