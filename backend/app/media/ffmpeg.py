"""FFmpeg/FFprobe helpers: probing, streaming progress, timeouts, cancellation."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Callable

from app.errors import FFMPEG_FAILED, ProcessingError

FFMPEG = os.environ.get("FFMPEG_BINARY", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BINARY", "ffprobe")

_FFMPEG_VERSION: str | None = None


def ffmpeg_available() -> tuple[bool, str | None]:
    global _FFMPEG_VERSION  # noqa: PLW0603
    path = shutil.which(FFMPEG)
    if not path:
        return False, None
    if _FFMPEG_VERSION is None:
        try:
            out = subprocess.run(
                [path, "-version"], capture_output=True, text=True, timeout=10
            ).stdout
            _FFMPEG_VERSION = out.splitlines()[0].strip() if out else "unknown"
        except Exception:  # pragma: no cover
            _FFMPEG_VERSION = "unknown"
    return True, _FFMPEG_VERSION


def ffprobe_json(path: Path) -> dict:
    """Return ffprobe -show_streams -show_format output as dict."""
    cmd = [
        FFPROBE, "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(FFMPEG_FAILED, "ffprobe timed out.") from exc
    if out.returncode != 0:
        raise ProcessingError(FFMPEG_FAILED, f"ffprobe failed: {out.stderr[:300]}")
    return json.loads(out.stdout or "{}")


def probe_duration(path: Path) -> float:
    data = ffprobe_json(path)
    fmt = data.get("format", {})
    try:
        return float(fmt.get("duration", 0.0))
    except (TypeError, ValueError):
        for st in data.get("streams", []):
            try:
                if st.get("duration"):
                    return float(st["duration"])
            except (TypeError, ValueError):
                continue
    return 0.0


def probe_streams(path: Path) -> list[dict]:
    return ffprobe_json(path).get("streams", [])


def has_stream(path: Path, codec_type: str) -> bool:
    return any(s.get("codec_type") == codec_type for s in probe_streams(path))


class FfmpegRunner:
    """Runs an ffmpeg command, streaming real progress from `-progress pipe:1`."""

    @staticmethod
    def run(
        args: list[str],
        *,
        duration_hint: float | None = None,
        progress: Callable[[float], None] | None = None,  # 0..1 within this ffmpeg step
        should_cancel: Callable[[], bool] | None = None,
        timeout_s: int = 3600,
        cwd: Path | None = None,
    ) -> None:
        base = [
            FFMPEG, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error",
            "-progress", "pipe:1", "-y",
        ]
        cmd = base + args
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(cwd) if cwd else None,
            start_new_session=True,
        )
        stderr_tail: list[str] = []
        out_time_re = re.compile(r"^out_time_us=(\d+)$")
        try:
            assert proc.stdout is not None and proc.stderr is not None
            import threading

            def _drain_stderr() -> None:
                for line in proc.stderr:  # type: ignore[union-attr]
                    if line.strip():
                        stderr_tail.append(line.strip())
                        if len(stderr_tail) > 30:
                            stderr_tail.pop(0)

            t = threading.Thread(target=_drain_stderr, daemon=True)
            t.start()

            import time as _time

            deadline = _time.monotonic() + timeout_s
            for line in proc.stdout:
                if should_cancel and should_cancel():
                    raise ProcessingError(FFMPEG_FAILED, "Conversion canceled.", details={"canceled": True})
                if _time.monotonic() > deadline:
                    raise ProcessingError(
                        FFMPEG_FAILED, f"ffmpeg exceeded the {timeout_s}s time limit and was stopped."
                    )
                m = out_time_re.match(line.strip())
                if m and duration_hint and duration_hint > 0 and progress:
                    frac = min(1.0, (int(m.group(1)) / 1e6) / duration_hint)
                    progress(max(0.0, frac))
            proc.wait(timeout=30)
        except ProcessingError:
            _kill_tree(proc)
            raise
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raise ProcessingError(FFMPEG_FAILED, f"ffmpeg timed out after {timeout_s}s.")
        except Exception as exc:
            _kill_tree(proc)
            raise ProcessingError(FFMPEG_FAILED, f"ffmpeg failed to run: {exc}") from exc
        finally:
            if proc.poll() is None:  # pragma: no cover
                _kill_tree(proc)

        if proc.returncode != 0:
            tail = "\n".join(stderr_tail[-6:])
            raise ProcessingError(FFMPEG_FAILED, f"ffmpeg exited with code {proc.returncode}: {tail[:600]}")


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:  # pragma: no cover
            pass
