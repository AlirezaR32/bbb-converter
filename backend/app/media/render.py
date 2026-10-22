"""Slide rendering: rasterize slide images (SVG/PNG), optionally composite
whiteboard annotations, and build the slide timeline video with FFmpeg."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Callable

import cairosvg

from app.bbb.parsing import SlideInterval, ShapeSpan, Timeline
from app.errors import RENDER_FAILED, ProcessingError

CANVAS_W, CANVAS_H = 1600, 900
SLIDE_FPS = 12


def rasterize_slide(src: Path, dst: Path, width: int = CANVAS_W) -> Path:
    """Rasterize a slide asset (SVG via cairosvg, images copied) to PNG."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower()
    try:
        if suffix == ".svg":
            cairosvg.svg2png(url=str(src), write_to=str(dst), output_width=width)
            return dst
        if suffix in (".png", ".jpg", ".jpeg"):
            shutil.copyfile(src, dst)
            return dst
        raise ProcessingError(RENDER_FAILED, f"Unsupported slide image format '{suffix}'.")
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(RENDER_FAILED, f"Failed to rasterize slide {src.name}: {exc}") from exc


def composite_slide_with_shapes(slide_png: Path, shapes: list[ShapeSpan], dst: Path,
                                shapes_view_box: str = "0 0 800 600") -> Path:
    """Overlay whiteboard annotation fragments onto a rasterized slide."""
    slide_b64 = base64.b64encode(slide_png.read_bytes()).decode()
    frags = "\n".join(s.xml for s in shapes)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{CANVAS_W}" height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}">'
        f'<image xlink:href="data:image/png;base64,{slide_b64}" '
        f'width="{CANVAS_W}" height="{CANVAS_H}" preserveAspectRatio="xMidYMid meet"/>'
        f'<svg width="{CANVAS_W}" height="{CANVAS_H}" viewBox="{shapes_view_box}" '
        f'preserveAspectRatio="xMidYMid meet">{frags}</svg></svg>'
    )
    try:
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(dst), output_width=CANVAS_W)
    except Exception as exc:
        raise ProcessingError(RENDER_FAILED, f"Annotation compositing failed: {exc}") from exc
    return dst


def merge_intervals(timeline: Timeline, duration: float) -> list[SlideInterval]:
    """Sort, clamp and gap-fill slide intervals for gapless rendering."""
    slides = sorted(
        (s for s in timeline.slides if s.end > s.start), key=lambda s: s.start
    )
    if not slides:
        return []
    merged: list[SlideInterval] = []
    for s in slides:
        start = min(s.start, duration)
        end = min(s.end, duration)
        if merged:
            prev = merged[-1]
            # Fill gaps by extending the previous slide.
            if start > prev.end:
                start = prev.end
            # Merge runs of the same slide asset.
            if s.href == prev.href and start <= prev.end:
                prev.end = max(prev.end, end)
                continue
        merged.append(SlideInterval(href=s.href, start=start, end=end,
                                    x=s.x, y=s.y, width=s.width, height=s.height))
    if merged:
        merged[0].start = 0.0
        merged[-1].end = duration
    return [m for m in merged if m.end - m.start > 0.05][:600]


def build_slide_video(
    intervals: list[SlideInterval],
    slide_pngs: dict[str, Path],
    out_path: Path,
    duration: float,
    *,
    progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    """Create the slide video: each slide shown (fitted & padded) for its interval."""
    from app.media.ffmpeg import FfmpegRunner

    if not intervals:
        raise ProcessingError(RENDER_FAILED, "No slide intervals to render.")

    inputs: list[str] = []
    filters: list[str] = []
    concat_labels: list[str] = []
    for i, iv in enumerate(intervals):
        png = slide_pngs.get(iv.href)
        if png is None or not png.exists():
            continue
        dur = max(0.1, iv.end - iv.start)
        inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]
        filters.append(
            f"[{len(concat_labels)}:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=decrease,"
            f"pad={CANVAS_W}:{CANVAS_H}:(ow-iw)/2:(oh-ih)/2:color=0x101318,setsar=1,fps={SLIDE_FPS}[s{i}]"
        )
        concat_labels.append(f"[s{i}]")

    if not concat_labels:
        raise ProcessingError(RENDER_FAILED, "None of the slide images could be prepared.")

    filter_complex = (
        ";".join(filters)
        + f";{''.join(concat_labels)}concat=n={len(concat_labels)}:v=1:a=0[v]"
    )
    args = inputs + [
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    FfmpegRunner.run(
        args,
        duration_hint=duration,
        progress=progress,
        should_cancel=should_cancel,
        timeout_s=3600,
    )


def extract_shapes_viewbox(shapes_svg_path: Path) -> str:
    try:
        import re

        head = shapes_svg_path.read_text(errors="ignore")[:2000]
        m = re.search(r'viewBox\s*=\s*"([^"]+)"', head)
        if m:
            return m.group(1)
    except Exception:  # pragma: no cover
        pass
    return "0 0 800 600"
