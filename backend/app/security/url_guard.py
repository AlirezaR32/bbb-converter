"""URL validation and SSRF protection.

All user-supplied recording URLs are untrusted. This module enforces:
- HTTPS-only by default (http allowed only when explicitly configured)
- Restriction to BigBlueButton playback path shapes
- Resolution of every DNS address to public, non-reserved IP space
- Blocking of localhost / private / link-local / cloud-metadata ranges
- Port allow-listing
- Prefix allow-list for the bundled demo recording (demo mode only)
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.config import Settings
from app.errors import (
    INVALID_URL,
    SSRF_BLOCKED,
    UNSUPPORTED_PLAYBACK_VERSION,
    UrlValidationError,
)

# BigBlueButton presentation playback paths: /playback/presentation/<version>/<record id>
PLAYBACK_PATH_RE_PARTS = ("playback", "presentation")
SUPPORTED_PLAYBACK_VERSIONS = ("2.0", "2.3")
RECORDING_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

# Cloud metadata endpoints that must never be reachable.
BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),  # AWS/GCP metadata
    ipaddress.ip_address("fd00:ec2::254"),    # AWS IPv6 metadata
    ipaddress.ip_address("100.100.100.200"),  # Alibaba metadata
}


@dataclass
class ParsedRecordingUrl:
    original_url: str
    normalized_url: str
    scheme: str
    host: str
    port: int
    playback_version: str
    meeting_id: str
    # Candidate roots that may hold the recording assets (playback path + raw published path).
    asset_roots: list[str] = field(default_factory=list)

    @property
    def server_host(self) -> str:
        return self.host


def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip in BLOCKED_IPS:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or getattr(ip, "is_global", True) is False
    )


def _parse_recording_path(path: str, demo_mode: bool = False) -> tuple[str, str]:
    """Return (playback_version, meeting_id) or raise UrlValidationError."""
    parts = [p for p in path.split("/") if p]
    # The bundled demo recording is served under /demo/playback/presentation/...
    if demo_mode and parts and parts[0] == "demo":
        parts = parts[1:]
    # Expect: playback / presentation / <version> / <id>
    if len(parts) < 4 or parts[0] != PLAYBACK_PATH_RE_PARTS[0] or parts[1] != PLAYBACK_PATH_RE_PARTS[1]:
        raise UrlValidationError(
            INVALID_URL,
            "URL is not a BigBlueButton presentation playback link. Expected shape: "
            "https://<server>/playback/presentation/2.3/<recording-id>",
        )
    version = parts[2]
    if version not in SUPPORTED_PLAYBACK_VERSIONS:
        raise UrlValidationError(
            UNSUPPORTED_PLAYBACK_VERSION,
            f"Unsupported playback version '{version}'. Supported versions: "
            + ", ".join(SUPPORTED_PLAYBACK_VERSIONS),
            details={"version": version},
        )
    meeting_id = parts[3]
    if not meeting_id or len(meeting_id) < 8 or not set(meeting_id) <= RECORDING_ID_CHARS:
        raise UrlValidationError(INVALID_URL, "Invalid recording identifier in URL.")
    return version, meeting_id


def _resolve_host_ips(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UrlValidationError(
            INVALID_URL, f"Cannot resolve host '{host}': {exc}"
        ) from exc
    ips: list[ipaddress._BaseAddress] = []
    for info in infos:
        addr = info[4][0]
        try:
            ips.append(ipaddress.ip_address(addr.split("%")[0]))
        except ValueError:  # pragma: no cover
            continue
    if not ips:
        raise UrlValidationError(INVALID_URL, f"Host '{host}' does not resolve to any address.")
    return ips


def validate_recording_url(raw_url: str, settings: Settings) -> ParsedRecordingUrl:
    """Validate a user-supplied playback URL. Raises UrlValidationError on any violation."""
    url = raw_url.strip()
    if not url:
        raise UrlValidationError(INVALID_URL, "URL is required.")
    if len(url) > 2048:
        raise UrlValidationError(INVALID_URL, "URL is too long.")
    if any(c.isspace() for c in url):
        raise UrlValidationError(INVALID_URL, "URL must not contain whitespace.")

    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("https", "http"):
        raise UrlValidationError(INVALID_URL, "Only HTTP/HTTPS URLs are supported.")

    host = parts.hostname
    if not host:
        raise UrlValidationError(INVALID_URL, "URL is missing a hostname.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise UrlValidationError(
            INVALID_URL, "URL must not contain credentials, query strings, or fragments."
        )
    host = host.rstrip(".")
    port = parts.port if parts.port is not None else (443 if scheme == "https" else 80)

    version, meeting_id = _parse_recording_path(parts.path, demo_mode=settings.demo_mode)

    prefix_allowed = any(
        url.rstrip("/").startswith(p.rstrip("/")) for p in settings.allowed_url_prefixes
    )

    if scheme == "http" and not settings.allow_insecure_http and not prefix_allowed:
        raise UrlValidationError(INVALID_URL, "Only HTTPS URLs are allowed (HTTP is disabled).")

    if not prefix_allowed:
        if port not in settings.allowed_port_set:
            raise UrlValidationError(
                SSRF_BLOCKED,
                f"Port {port} is not allowed. Only ports {sorted(settings.allowed_port_set)} are permitted.",
            )
        # Try to resolve the host and validate every address (SSRF guard).
        try:
            ips = _resolve_host_ips(host)
        except UrlValidationError:
            # Literal IPv4/IPv6 host: validate directly.
            try:
                ips = [ipaddress.ip_address(host)]
            except ValueError as exc:
                raise UrlValidationError(INVALID_URL, f"Invalid host '{host}'.") from exc
        blocked = [str(ip) for ip in ips if _is_ip_blocked(ip)]
        if blocked:
            raise UrlValidationError(
                SSRF_BLOCKED,
                "Refusing to fetch from private, local, or metadata addresses.",
                details={"blocked_addresses": blocked[:8]},
            )

    origin = f"{scheme}://{host}" + (f":{port}" if port not in (80, 443) else "")
    # Keep the /demo prefix when the URL points at the bundled demo recording.
    demo_prefix = "/demo" if settings.demo_mode and parts.path.startswith("/demo/") else ""
    parsed = ParsedRecordingUrl(
        original_url=raw_url.strip(),
        normalized_url=f"{origin}{demo_prefix}/playback/presentation/{version}/{meeting_id}",
        scheme=scheme,
        host=host,
        port=port,
        playback_version=version,
        meeting_id=meeting_id,
    )
    # Asset roots: (1) the playback path itself, (2) canonical published-recordings path.
    parsed.asset_roots = [
        parsed.normalized_url,
        f"{origin}{demo_prefix}/presentation/{meeting_id}",
    ]
    return parsed


def validate_redirect_url(url: str, settings: Settings) -> None:
    """Validate each redirect hop (same rules, but query strings are allowed)."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("https", "http"):
        raise UrlValidationError(SSRF_BLOCKED, f"Redirect to non-HTTP(S) scheme blocked: {scheme!r}")
    if scheme == "http" and not settings.allow_insecure_http:
        raise UrlValidationError(SSRF_BLOCKED, "Redirect to plain HTTP blocked.")
    host = parts.hostname
    if not host:
        raise UrlValidationError(SSRF_BLOCKED, "Redirect URL is missing a hostname.")
    host = host.rstrip(".")
    port = parts.port if parts.port is not None else (443 if scheme == "https" else 80)

    prefix_allowed = any(url.rstrip("/").startswith(p.rstrip("/")) for p in settings.allowed_url_prefixes)
    if prefix_allowed:
        return
    if port not in settings.allowed_port_set:
        raise UrlValidationError(SSRF_BLOCKED, f"Redirect to disallowed port {port} blocked.")
    try:
        ips = _resolve_host_ips(host)
    except UrlValidationError:
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError as exc:
            raise UrlValidationError(SSRF_BLOCKED, "Redirect to unresolvable host blocked.") from exc
    blocked = [str(ip) for ip in ips if _is_ip_blocked(ip)]
    if blocked:
        raise UrlValidationError(
            SSRF_BLOCKED,
            "Redirect to private, local, or metadata address blocked.",
            details={"blocked_addresses": blocked[:8]},
        )
