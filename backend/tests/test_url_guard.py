"""URL validation + SSRF protection tests (DNS is mocked for offline runs)."""

from __future__ import annotations

import ipaddress

import pytest

from app.config import get_settings
from app.errors import UrlValidationError
from app.security import url_guard
from app.security.url_guard import validate_recording_url

VALID_23 = "https://bbb.example.edu/playback/presentation/2.3/1fcdf8dc9c9be19604bf7cb70b0488c2909f8ec5-1791645760902"
VALID_20 = "https://bbb.example.edu/playback/presentation/2.0/abcd1234abcd1234abcd1234abcd1234abcd1234-1700000000000"

PUBLIC_IP = ipaddress.ip_address("93.184.216.34")


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """Resolve every hostname to a public IP so tests never touch real DNS."""

    def _fake(host: str):
        # Literal IPs resolve to themselves (so private-IP tests still block).
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            if host == "localhost":
                return [ipaddress.ip_address("127.0.0.1")]
            return [PUBLIC_IP]

    monkeypatch.setattr(url_guard, "_resolve_host_ips", _fake)
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", lambda *a, **k: [])


def test_valid_23_url_parses():
    p = validate_recording_url(VALID_23, get_settings())
    assert p.meeting_id == "1fcdf8dc9c9be19604bf7cb70b0488c2909f8ec5-1791645760902"
    assert p.playback_version == "2.3"
    assert p.server_host == "bbb.example.edu"
    assert len(p.asset_roots) == 2
    assert p.asset_roots[1].endswith("/presentation/" + p.meeting_id)


def test_valid_20_url_parses():
    p = validate_recording_url(VALID_20, get_settings())
    assert p.playback_version == "2.0"


def test_rejects_non_http_scheme():
    with pytest.raises(UrlValidationError):
        validate_recording_url("ftp://bbb.example.edu/playback/presentation/2.3/abcdefgh12345678", get_settings())


def test_rejects_plain_http_by_default():
    with pytest.raises(UrlValidationError) as e:
        validate_recording_url(
            "http://bbb.example.edu/playback/presentation/2.3/abcdefgh12345678", get_settings()
        )
    assert "HTTPS" in e.value.message


def test_rejects_wrong_path():
    for url in [
        "https://bbb.example.edu/some/other/path",
        "https://bbb.example.edu/playback/presentation/2.3/",
        "https://bbb.example.edu/playback/other/2.3/abcdefgh12345678",
    ]:
        with pytest.raises(UrlValidationError):
            validate_recording_url(url, get_settings())


def test_rejects_unsupported_version():
    with pytest.raises(UrlValidationError) as e:
        validate_recording_url(
            "https://bbb.example.edu/playback/presentation/9.9/abcdefgh12345678", get_settings()
        )
    assert e.value.code == "UNSUPPORTED_PLAYBACK_VERSION"


def test_rejects_localhost_and_private_ips():
    urls = [
        "https://localhost/playback/presentation/2.3/abcdefgh12345678",
        "https://127.0.0.1/playback/presentation/2.3/abcdefgh12345678",
        "https://10.1.2.3/playback/presentation/2.3/abcdefgh12345678",
        "https://192.168.1.10/playback/presentation/2.3/abcdefgh12345678",
        "https://172.16.0.9/playback/presentation/2.3/abcdefgh12345678",
        "https://169.254.169.254/playback/presentation/2.3/abcdefgh12345678",
        "https://[::1]/playback/presentation/2.3/abcdefgh12345678",
        "https://[fd00::1]/playback/presentation/2.3/abcdefgh12345678",
    ]
    for url in urls:
        with pytest.raises(UrlValidationError) as e:
            validate_recording_url(url, get_settings())
        assert e.value.code in ("SSRF_BLOCKED", "INVALID_URL"), url


def test_rejects_disallowed_port():
    with pytest.raises(UrlValidationError) as e:
        validate_recording_url(
            "https://bbb.example.edu:8080/playback/presentation/2.3/abcdefgh12345678",
            get_settings(),
        )
    assert e.value.code == "SSRF_BLOCKED"


def test_rejects_credentials_and_query():
    with pytest.raises(UrlValidationError):
        validate_recording_url(
            "https://user:pass@bbb.example.edu/playback/presentation/2.3/abcdefgh12345678",
            get_settings(),
        )
    with pytest.raises(UrlValidationError):
        validate_recording_url(VALID_23 + "?x=1", get_settings())


def test_demo_prefix_bypasses_checks():
    settings = get_settings()
    demo_url = settings.demo_recording_url
    p = validate_recording_url(demo_url, settings)
    assert p.meeting_id == settings.demo_recording_id
