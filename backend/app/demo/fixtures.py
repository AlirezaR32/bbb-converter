"""Demo mode: generate a synthetic BigBlueButton recording bundle.

The fixture mimics a real published recording (metadata.xml, shapes.svg with a
slide timeline, audio/webcam media files) so the full pipeline — inspection,
download, reconstruction — is exercised end-to-end without any external server.
It is served under /demo/** and only reachable when settings.demo_mode is true.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.config import Settings

log = logging.getLogger("bbb.demo")

DECK_ID = "dem0deck00000000000000000000000000000000-1700000000000"

SLIDE_TITLES = [
    ("Welcome to the Demo Lecture", "BigBlueButton Recording Converter"),
    ("How Reconstruction Works", "slides + annotations + webcam + audio"),
    ("Questions?", "Thank you for watching"),
]
DURATION = 66.0  # seconds (slide1: 0-30, slide2: 30-52, slide3: 52-66)


def _ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True, timeout=300)


def _make_slides(dir_png: Path, dir_svg: Path) -> None:
    import cairosvg

    dir_png.mkdir(parents=True, exist_ok=True)
    dir_svg.mkdir(parents=True, exist_ok=True)
    palette = [("#151a2b", "#7c5cff"), ("#12222b", "#22c55e"), ("#241527", "#ec4899")]
    for i, (title, sub) in enumerate(SLIDE_TITLES, start=1):
        bg, accent = palette[(i - 1) % len(palette)]
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" '
            'viewBox="0 0 1600 900">'
            f'<rect width="1600" height="900" fill="{bg}"/>'
            f'<rect x="0" y="620" width="1600" height="8" fill="{accent}"/>'
            f'<text x="110" y="330" font-family="DejaVu Sans" font-weight="bold" '
            f'font-size="72" fill="#f2f4fa">{title}</text>'
            f'<text x="110" y="420" font-family="DejaVu Sans" font-size="40" '
            f'fill="{accent}">{sub}</text>'
            f'<text x="110" y="800" font-family="DejaVu Sans" font-size="26" '
            f'fill="#5c637a">Synthetic demo recording generated with FFmpeg — slide {i}/3</text>'
            f'<circle cx="1400" cy="220" r="120" fill="none" stroke="{accent}" stroke-width="6"/>'
            f'<text x="1400" y="240" font-family="DejaVu Sans" font-size="56" fill="{accent}" '
            f'text-anchor="middle">{i}</text>'
            '</svg>'
        )
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(dir_png / f"slide{i}.png"),
                         output_width=1600)
        (dir_svg / f"slide{i}.svg").write_text(svg)


def _make_media(rec_dir: Path) -> None:
    audio_dir = rec_dir / "audio"
    video_dir = rec_dir / "video"
    audio_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)
    # gentle dual-tone audio (opus/webm)
    _ffmpeg([
        "-f", "lavfi", "-i",
        "sine=frequency=330:duration=66:sample_rate=44100",
        "-f", "lavfi", "-i",
        "sine=frequency=550:duration=66:sample_rate=44100",
        "-filter_complex", "[0:a][1:a]amix=inputs=2,volume=0.4[a]",
        "-map", "[a]", "-c:a", "libopus", "-b:a", "96k",
        str(audio_dir / "audio.webm"),
    ])
    # animated "webcam": test pattern with moving box (vp8 + embedded audio)
    _ffmpeg([
        "-f", "lavfi", "-i",
        "testsrc2=size=640x480:rate=15:duration=66",
        "-f", "lavfi", "-i",
        "sine=frequency=220:duration=66:sample_rate=44100",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libvpx", "-b:v", "300k", "-deadline", "good", "-cpu-used", "8",
        "-c:a", "libvorbis", "-q:a", "3",
        str(video_dir / "webcams.webm"),
    ])


def _write_xml(rec_dir: Path, settings: Settings) -> None:
    dur_ms = int(DURATION * 1000)
    rec_id = settings.demo_recording_id
    metadata = f"""<?xml version='1.0' encoding='UTF-8'?>
<recording>
  <id>{rec_id}</id>
  <state>published</state>
  <published>true</published>
  <start_time>1700000000000</start_time>
  <end_time>{1700000000000 + dur_ms}</end_time>
  <participants>3</participants>
  <meeting id="{rec_id}" externalId="demo-external-id" name="Demo Lecture — BBB Converter" breakout="false"></meeting>
  <meta>
    <meetingName>Demo Lecture — BBB Converter</meetingName>
    <bbb-origin-version>demo-3.0</bbb-origin-version>
  </meta>
  <playback>
    <format>presentation</format>
    <link>{settings.demo_recording_url}</link>
    <duration>{dur_ms}</duration>
    <size>1000000</size>
  </playback>
</recording>"""
    (rec_dir / "metadata.xml").write_text(metadata)

    slides = [
        ("slide1.svg", 0.0, 30.0),
        ("slide2.svg", 30.0, 52.0),
        ("slide3.svg", 52.0, DURATION),
    ]
    imgs = "\n".join(
        f'  <image id="image{i}" class="slide" in="{a}" out="{b}" '
        f'xlink:href="presentation/{DECK_ID}/svgs/{name}" width="1600" height="900" '
        f'x="0" y="0" style="visibility:hidden"/>'
        for i, (name, a, b) in enumerate(slides, start=1)
    )
    shapes_svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'id="svgfile" style="position:absolute;height:600px;width:800px" version="1.1" '
        'viewBox="0 0 800 600">\n' + imgs + "\n</svg>"
    )
    (rec_dir / "shapes.svg").write_text(shapes_svg)

    index_html = (
        "<!doctype html><html><head><title>BBB Demo Playback</title></head>"
        "<body><h1>BigBlueButton Demo Recording</h1>"
        "<p>This is a synthetic recording served by the converter's demo mode.</p>"
        f"<p>Recording id: {rec_id}</p></body></html>"
    )
    (rec_dir / "index.html").write_text(index_html)


def ensure_demo_recording(settings: Settings) -> Path:
    """Generate (idempotently) the demo recording tree; returns the asset root."""
    root = settings.demo_dir  # .../data/demo
    playback_root = root / "playback" / "presentation" / "2.3"
    rec_dir = root / "presentation" / settings.demo_recording_id
    marker = rec_dir / ".complete"

    if marker.exists():
        return rec_dir

    log.info("generating demo recording fixtures in %s", rec_dir)
    deck = rec_dir / "presentation" / DECK_ID
    _make_slides(deck / "png", deck / "svgs")
    _make_media(rec_dir)
    _write_xml(rec_dir, settings)
    marker.write_text("ok")

    # playback path mirrors metadata.xml + index.html only (like real BBB
    # servers where the playback alias serves the page but media lives under
    # /presentation/<id>/). shapes.svg is intentionally NOT mirrored here so
    # relative slide hrefs resolve against the media root.
    try:
        playback_rec = playback_root / settings.demo_recording_id
        playback_rec.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rec_dir / "metadata.xml", playback_rec / "metadata.xml")
        shutil.copyfile(rec_dir / "index.html", playback_rec / "index.html")
    except Exception:  # pragma: no cover
        log.exception("failed to mirror demo playback files")

    return rec_dir
