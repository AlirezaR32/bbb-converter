"""Unit tests for the slide rendering helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.bbb.parsing import SlideInterval, Timeline
from app.errors import ProcessingError
from app.media.render import merge_intervals, rasterize_slide


def _svg(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">'
        '<rect width="1600" height="900" fill="#223"/>'
        '<text x="100" y="200" font-size="60" fill="#fff">Unit test slide</text></svg>'
    )
    return path


def test_merge_intervals_gap_fill_and_clamp():
    tl = Timeline()
    tl.slides = [
        SlideInterval(href="a.svg", start=0, end=30),
        SlideInterval(href="b.svg", start=35, end=60),  # gap 30-35
        SlideInterval(href="b.svg", start=60, end=120),  # beyond duration
    ]
    out = merge_intervals(tl, duration=100)
    assert out[0].start == 0
    assert out[0].end == 30
    # gap filled by extending previous slide
    assert out[1].start == 30
    # clamped to duration; runs of same asset merged
    assert out[-1].end == 100
    assert all(i.end > i.start for i in out)


def test_rasterize_svg_to_png(tmp_path):
    src = _svg(tmp_path / "slide.svg")
    dst = tmp_path / "slide.png"
    rasterize_slide(src, dst, width=800)
    assert dst.exists() and dst.stat().st_size > 1000


def test_rasterize_unsupported(tmp_path):
    src = tmp_path / "slide.bmp"
    src.write_bytes(b"BMxxxx")
    with pytest.raises(ProcessingError):
        rasterize_slide(src, tmp_path / "out.png")
