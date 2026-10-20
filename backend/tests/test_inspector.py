"""Recording inspection tests against a local fake BBB origin."""

from __future__ import annotations

import pytest

from app.bbb.inspector import RecordingInspector
from app.config import get_settings
from app.errors import SourceError
from app.security.fetcher import SafeFetcher
from app.security.url_guard import validate_recording_url


def _inspect(demo_server: str, path: str = "/demo/playback/presentation/2.3/"
             "dem0recording0000000000000000000000000000000-1700000000000"):
    settings = get_settings()
    parsed = validate_recording_url(demo_server + path, settings)
    fetcher = SafeFetcher(settings)
    try:
        return RecordingInspector(settings, fetcher).inspect(parsed), parsed
    finally:
        fetcher.close()


def test_inspect_demo_recording(demo_server):
    insp, parsed = _inspect(demo_server)
    assert insp.title == "Demo Lecture — BBB Converter"
    assert insp.duration_seconds == 66.0
    assert insp.webcam.available
    assert insp.audio.available
    assert not insp.direct_video.available
    assert len(insp.timeline.slides) == 3
    assert insp.strategy["id"] == "reconstruct"
    assert insp.strategy["supported"] is True


def test_inspect_reports_assets(demo_server):
    insp, _ = _inspect(demo_server)
    assets = insp.assets_dict()
    assert assets["webcam"]["available"] is True
    assert "webm" in (assets["webcam"]["content_type"] or "")
    assert assets["slides"]["count"] == 3
    assert assets["slides"]["format"] == "svg"


def test_inspect_unsupported_recording(demo_server):
    """A recording id with no media at all must fail with a clear error."""
    with pytest.raises(SourceError) as e:
        _inspect(demo_server, "/demo/playback/presentation/2.3/no0000such0000000000000000000000rec0rding-1700000000000")
    assert e.value.code == "ASSETS_MISSING"


def test_internal_dict_carries_timeline(demo_server):
    insp, _ = _inspect(demo_server)
    d = insp.to_dict(internal=True)
    assert d["timeline"]["slide_hrefs"]
    assert d["timeline_base_url"]
    assert d["asset_root"]
    # public dict must NOT leak internals
    pub = insp.to_dict()
    assert "timeline" not in pub
