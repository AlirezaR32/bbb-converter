"""SSRF-aware HTTP client used for every remote request.

- Manual redirect handling: every hop is re-validated against the SSRF guard.
- Streaming downloads straight to disk (never buffering whole files in memory).
- Size caps and timeouts on every transfer.
- Soft-404 detection helper: many BBB servers fall back to the SPA index.html
  with HTTP 200; callers can detect that via content type mismatches.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import httpx

from app.config import Settings
from app.errors import (
    SOURCE_ERROR,
    SOURCE_FORBIDDEN,
    SOURCE_TIMEOUT,
    SOURCE_UNREACHABLE,
    TLS_ERROR,
    SSRF_BLOCKED,
    SourceError,
)
from app.security.url_guard import validate_redirect_url

USER_AGENT = "BBB-Recording-Converter/1.0 (+media-archiver; respects robots & access rules)"


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    data: bytes

    @property
    def looks_like_html(self) -> bool:
        ct = (self.content_type or "").lower()
        return "text/html" in ct or "application/xhtml" in ct


class SafeFetcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.Client(
            follow_redirects=False,
            verify=settings.verify_tls,
            timeout=httpx.Timeout(settings.request_timeout_s, connect=10.0),
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            http2=False,
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    def _request_following_redirects(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        seen = 0
        current = url
        last_resp: httpx.Response | None = None
        while True:
            try:
                resp = self._client.request(method, current, headers=headers)
            except httpx.TimeoutException as exc:
                raise SourceError(SOURCE_TIMEOUT, f"The server did not respond in time ({current}).") from exc
            except httpx.ConnectError as exc:
                raise SourceError(SOURCE_UNREACHABLE, f"Could not connect to the recording server ({current}).") from exc
            except httpx.TooManyRedirects as exc:  # pragma: no cover
                raise SourceError(SOURCE_ERROR, "Too many redirects.") from exc
            except httpx.HTTPError as exc:
                msg = str(exc)
                code = TLS_ERROR if ("certificate" in msg.lower() or "ssl" in msg.lower()) else SOURCE_ERROR
                raise SourceError(code, f"Request to the recording server failed: {msg[:300]}") from exc

            if resp.is_redirect:
                seen += 1
                if seen > self.settings.max_redirects:
                    raise SourceError(SOURCE_ERROR, "Too many redirects.")
                loc = resp.headers.get("location")
                if not loc:
                    raise SourceError(SOURCE_ERROR, "Redirect without a Location header.")
                from urllib.parse import urljoin

                nxt = urljoin(current, loc)
                try:
                    validate_redirect_url(nxt, self.settings)
                except Exception as exc:
                    raise SourceError(
                        SSRF_BLOCKED, f"Redirect target rejected for security reasons: {exc.message if hasattr(exc, 'message') else exc}"
                    ) from exc
                current = nxt
                continue
            last_resp = resp
            break
        assert last_resp is not None
        return last_resp

    # ------------------------------------------------------------------
    def fetch(self, url: str, *, max_bytes: int | None = None) -> FetchResult:
        """GET a (small) resource fully into memory with a hard size cap."""
        cap = max_bytes or (16 * 1024 * 1024)
        resp = self._request_following_redirects("GET", url, headers={"Accept-Encoding": "identity"})
        if resp.status_code in (401, 403):
            raise SourceError(SOURCE_FORBIDDEN, f"The server refused access to {url} (HTTP {resp.status_code}).")
        if resp.status_code != 200:
            raise SourceError(SOURCE_ERROR, f"Unexpected HTTP {resp.status_code} for {url}.")
        length = resp.headers.get("content-length")
        if length and int(length) > cap:
            raise SourceError(SOURCE_ERROR, f"Resource at {url} is too large (>{cap // (1024 * 1024)} MB).")
        data = resp.content[: cap + 1]
        if len(data) > cap:
            raise SourceError(SOURCE_ERROR, f"Resource at {url} exceeded the {cap // (1024 * 1024)} MB limit.")
        return FetchResult(
            url=url,
            final_url=str(resp.request.url),
            status_code=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            data=data,
        )

    def head(self, url: str) -> tuple[int, str, int | None]:
        """HEAD request -> (status, content_type, content_length)."""
        try:
            resp = self._request_following_redirects("HEAD", url)
        except SourceError as exc:
            if exc.code in (SOURCE_TIMEOUT, SOURCE_UNREACHABLE, TLS_ERROR, SSRF_BLOCKED, SOURCE_FORBIDDEN):
                raise
            # Some servers choke on HEAD; treat as not-found for probing purposes.
            return (exc.http_status, "", None)
        length = resp.headers.get("content-length")
        return (resp.status_code, resp.headers.get("content-type", ""), int(length) if length else None)

    # ------------------------------------------------------------------
    def download_to_file(
        self,
        url: str,
        dest: Path,
        *,
        max_bytes: int,
        progress: Callable[[int, int | None], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        """Stream a (possibly large) asset to disk. Returns the written path."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._client.stream("GET", url, timeout=httpx.Timeout(self.settings.download_timeout_s, connect=15.0)) as resp:
            if resp.status_code in (401, 403):
                raise SourceError(SOURCE_FORBIDDEN, f"The server refused access to {url} (HTTP {resp.status_code}).")
            if resp.status_code != 200:
                raise SourceError(SOURCE_ERROR, f"Unexpected HTTP {resp.status_code} while downloading {url}.")
            total = resp.headers.get("content-length")
            total = int(total) if total else None
            if total and total > max_bytes:
                raise SourceError(
                    SOURCE_ERROR,
                    f"Asset at {url} is {total // (1024 * 1024)} MB which exceeds the configured limit "
                    f"of {max_bytes // (1024 * 1024)} MB.",
                )
            written = 0
            tmp = dest.with_suffix(dest.suffix + ".part")
            try:
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                        if should_cancel and should_cancel():
                            raise SourceError(SOURCE_ERROR, "Download canceled.", details={"canceled": True})
                        written += len(chunk)
                        if written > max_bytes:
                            raise SourceError(
                                SOURCE_ERROR,
                                f"Asset at {url} exceeded the {max_bytes // (1024 * 1024)} MB download limit.",
                            )
                        fh.write(chunk)
                        if progress:
                            progress(written, total)
                shutil.move(tmp, dest)
            finally:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
        return dest


def soft404(content_type: str, expected_prefixes: tuple[str, ...]) -> bool:
    """True when the server answered 200 with an unrelated content type
    (typical BBB SPA fallback: every URL returns the playback index.html)."""
    ct = (content_type or "").lower().split(";")[0].strip()
    if not ct:
        return False
    return not any(ct.startswith(p) for p in expected_prefixes)
