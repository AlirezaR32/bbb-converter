"""Debug the test demo server behaviour (run standalone)."""

import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

os.environ["DATA_DIR"] = "/tmp/bbb-dbg3"
os.environ["DATABASE_URL"] = "sqlite:////tmp/bbb-dbg3/t.db"
os.environ["BACKEND_PUBLIC_URL"] = "http://127.0.0.1:8765"
os.environ["DEMO_MODE"] = "true"

from app.config import get_settings  # noqa: E402
from app.demo.fixtures import ensure_demo_recording  # noqa: E402

s = get_settings()
print("demo dir:", s.demo_dir, flush=True)
print("demo url:", s.demo_recording_url, flush=True)
rec = ensure_demo_recording(s)
print("generated at:", rec, flush=True)
print("contents:", sorted(str(p.relative_to(s.demo_dir)) for p in s.demo_dir.rglob("*"))[:20], flush=True)


class H(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/demo/"):
            path = path[len("/demo"):]
        elif path == "/demo":
            path = "/"
        return super().translate_path(path)

    def log_message(self, *a):
        pass


H.directory = str(s.demo_dir)
httpd = ThreadingHTTPServer(("127.0.0.1", 8765), H)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

import httpx  # noqa: E402

c = httpx.Client(timeout=15)
base = "http://127.0.0.1:8765/demo/playback/presentation/2.3/dem0recording0000000000000000000000000000000-1700000000000"
for rel in ["metadata.xml", "index.html"]:
    r = c.head(f"{base}/{rel}")
    print("HEAD", rel, "->", r.status_code, r.headers.get("content-type"), flush=True)
root2 = "http://127.0.0.1:8765/demo/presentation/dem0recording0000000000000000000000000000000-1700000000000"
for rel in ["video/webcams.webm", "audio/audio.webm", "shapes.svg"]:
    r = c.head(f"{root2}/{rel}")
    print("HEAD", rel, "->", r.status_code, r.headers.get("content-type"), flush=True)
print("OK", flush=True)
