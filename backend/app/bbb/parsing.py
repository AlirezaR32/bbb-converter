"""Parsers for BigBlueButton recording artifacts.

BigBlueButton "presentation" playback is a synchronized bundle:
- metadata.xml            → meeting metadata + duration
- shapes.svg              → slide timeline (<image class="slide" in out xlink:href>),
                            whiteboard annotations (<g class="shape" ...>)
- slides_new.xml          → alternative slide timeline (older processing)
- panzooms.xml / cursors.xml / presentation_text.json → auxiliary event data
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

NS = {
    "svg": "http://www.w3.org/2000/svg",
    "xlink": "http://www.w3.org/1999/xlink",
}


@dataclass
class SlideInterval:
    href: str                 # asset-relative URL of the slide image
    start: float
    end: float
    x: float = 0.0
    y: float = 0.0
    width: float | None = None
    height: float | None = None


@dataclass
class ShapeSpan:
    """A whiteboard annotation visible between `start` and `end`."""

    start: float
    end: float
    xml: str                  # serialized SVG fragment


@dataclass
class Timeline:
    slides: list[SlideInterval] = field(default_factory=list)
    shapes: list[ShapeSpan] = field(default_factory=list)
    source: str = ""          # "shapes.svg" | "slides_new.xml"

    @property
    def unique_slide_hrefs(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.slides:
            seen.setdefault(s.href, None)
        return list(seen.keys())

    def clamp(self, duration: float) -> None:
        """Clamp slide intervals to the actual media duration."""
        if duration <= 0:
            return
        for s in self.slides:
            s.end = min(s.end, duration)
            s.start = min(s.start, s.end)


def parse_metadata_xml(data: bytes) -> dict:
    """Parse recording metadata.xml → dict with normalized fields."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(f"metadata.xml is not valid XML: {exc}") from exc
    if root.tag != "recording":
        raise ValueError("metadata.xml has unexpected root element (expected <recording>).")

    out: dict = {"title": "", "duration_seconds": 0.0, "start_time": "", "meeting_id": "",
                 "participants": None, "playback_link": ""}

    def _txt(el):  # noqa: ANN001
        return (el.text or "").strip() if el is not None else ""

    start_el = root.find("start_time")
    if start_el is not None and _txt(start_el).isdigit():
        ms = int(_txt(start_el))
        end_el = root.find("end_time")
        end_ms = int(_txt(end_el)) if end_el is not None and _txt(end_el).isdigit() else ms
        out["start_time"] = str(ms)
        if end_ms > ms:
            out["duration_seconds"] = (end_ms - ms) / 1000.0

    meeting = root.find("meeting")
    if meeting is not None:
        out["title"] = meeting.get("name") or _txt(meeting.find("meetingName")) or ""
        out["meeting_id"] = meeting.get("externalId") or meeting.get("id") or out["meeting_id"]

    meta = root.find("meta")
    if meta is not None:
        if not out["title"]:
            out["title"] = _txt(meta.find("meetingName")) or _txt(meta.find("bbb-context-name"))
        part = _txt(meta.find("participants"))
        if part.isdigit():
            out["participants"] = int(part)

    part_el = root.find("participants")
    if out["participants"] is None and part_el is not None and _txt(part_el).isdigit():
        out["participants"] = int(_txt(part_el))

    playback = root.find("playback")
    if playback is not None:
        dur = _txt(playback.find("duration"))
        if dur.isdigit():
            # metadata duration is milliseconds
            out["duration_seconds"] = max(out["duration_seconds"], int(dur) / 1000.0)
        link = _txt(playback.find("link"))
        if link:
            out["playback_link"] = link
    return out


def _num(el, attr: str, default: float = 0.0) -> float:  # noqa: ANN001
    try:
        return float(el.get(attr, default))
    except (TypeError, ValueError):
        return default


def parse_shapes_svg(data: bytes) -> Timeline:
    """Parse shapes.svg: slide intervals + whiteboard annotation spans."""
    tl = Timeline(source="shapes.svg")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(f"shapes.svg is not valid XML: {exc}") from exc

    for img in root.iter("{%s}image" % NS["svg"]):
        cls = (img.get("class") or "").lower()
        href = img.get("{%s}href" % NS["xlink"]) or img.get("href") or ""
        if "slide" in cls and href:
            tl.slides.append(
                SlideInterval(
                    href=href.strip(),
                    start=_num(img, "in"),
                    end=_num(img, "out"),
                    x=_num(img, "x"),
                    y=_num(img, "y"),
                    width=_num(img, "width") or None,
                    height=_num(img, "height") or None,
                )
            )
    tl.slides.sort(key=lambda s: s.start)
    return tl


def parse_slides_new_xml(data: bytes) -> Timeline:
    """Parse slides_new.xml (classic presentation processing)."""
    tl = Timeline(source="slides_new.xml")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(f"slides_new.xml is not valid XML: {exc}") from exc
    for slide in root.iter("slide"):
        img = slide.find("image")
        if img is None or not (img.text or "").strip():
            continue
        tl.slides.append(
            SlideInterval(
                href=(img.text or "").strip(),
                start=_num(slide, "in"),
                end=_num(slide, "out"),
            )
        )
    tl.slides.sort(key=lambda s: s.start)
    return tl


def extract_shape_spans(data: bytes, max_shapes: int = 4000) -> list[ShapeSpan]:
    """Extract annotation <g class="shape"> fragments with their visibility windows."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    shapes: list[ShapeSpan] = []
    for g in root.iter("{%s}g" % NS["svg"]):
        cls = (g.get("class") or "").lower()
        if "shape" not in cls:
            continue
        start = _num(g, "in", _num(g, "timestamp"))
        out_attr = g.get("out") or g.get("undo")
        try:
            end = float(out_attr) if out_attr else float("inf")
        except ValueError:
            end = float("inf")
        # Serialize the fragment back to a standalone SVG snippet.
        try:
            frag = ElementTree.tostring(g, encoding="unicode")
        except Exception:  # pragma: no cover
            continue
        shapes.append(ShapeSpan(start=start, end=end, xml=frag))
        if len(shapes) >= max_shapes:
            break
    return shapes


_SHAPE_URL_RE = re.compile(r"^(?!https?://)(?!data:)")


def is_relative_asset(url: str) -> bool:
    return bool(_SHAPE_URL_RE.match(url or ""))
