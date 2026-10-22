"""Recording inspection: discover what a BigBlueButton playback URL actually exposes.

Strategy (see README §BigBlueButton compatibility):
1. Probe candidate asset locations under the playback path AND the canonical
   `/presentation/<id>` published path (many servers only expose one of them,
   and some serve the SPA index.html as a soft-404 fallback for everything).
2. Validate content types strictly — an HTTP 200 with text/html is NOT media.
3. Parse metadata.xml + the slide timeline (shapes.svg, fallback slides_new.xml).
4. Select the best reconstruction strategy and produce an honest capability
   report including limitations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.bbb.parsing import (
    Timeline,
    extract_shape_spans,
    parse_metadata_xml,
    parse_shapes_svg,
    parse_slides_new_xml,
)
from app.config import Settings
from app.errors import ASSETS_MISSING, SOURCE_ERROR, SourceError
from app.security.fetcher import FetchResult, SafeFetcher, soft404
from app.security.url_guard import ParsedRecordingUrl

XML_CT = ("text/xml", "application/xml")
MEDIA_CT = ("video/", "audio/")
IMAGE_CT = ("image/",)
ANY_CT = XML_CT + MEDIA_CT + IMAGE_CT + ("application/json", "text/vtt", "application/octet-stream")


@dataclass
class ProbeResult:
    available: bool = False
    url: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    note: str | None = None


@dataclass
class Inspection:
    url: str
    server_host: str
    meeting_id: str
    playback_version: str
    asset_root: str
    title: str = ""
    duration_seconds: float = 0.0
    participants: int | None = None
    start_time: str | None = None
    direct_video: ProbeResult = field(default_factory=ProbeResult)
    webcam: ProbeResult = field(default_factory=ProbeResult)
    screenshare: ProbeResult = field(default_factory=ProbeResult)
    audio: ProbeResult = field(default_factory=ProbeResult)
    timeline: Timeline = field(default_factory=Timeline)
    timeline_base_url: str = ""  # base URL for resolving relative slide hrefs
    asset_roots: list[str] = field(default_factory=list)
    has_annotations: bool = False
    warnings: list[str] = field(default_factory=list)
    strategy: dict = field(default_factory=dict)
    estimated_output_mb: dict[str, float] = field(default_factory=dict)

    def assets_dict(self) -> dict:
        return {
            "direct_video": asdict(self.direct_video),
            "webcam": asdict(self.webcam),
            "screenshare": asdict(self.screenshare),
            "audio": asdict(self.audio),
            "slides": {
                "available": bool(self.timeline.slides),
                "count": len(self.timeline.slides),
                "unique": len(self.timeline.unique_slide_hrefs),
                "format": self._slide_format(),
                "source": self.timeline.source or None,
            },
            "annotations": {"available": self.has_annotations},
            "panzooms": "event data present in recording (not rendered in v1 pipeline)"
            if self.timeline.source else "unknown",
        }

    def _slide_format(self) -> str | None:
        for href in self.timeline.unique_slide_hrefs[:3]:
            low = href.lower()
            if low.endswith(".svg"):
                return "svg"
            if low.endswith(".png"):
                return "png"
            if low.endswith((".jpg", ".jpeg")):
                return "jpeg"
        return None

    def to_dict(self, internal: bool = False) -> dict:
        assets = self.assets_dict()
        slides = assets.get("slides", {})
        out = {
            "url": self.url,
            "server_host": self.server_host,
            "meeting_id": self.meeting_id,
            "playback_version": self.playback_version,
            "title": self.title,
            "duration_seconds": self.duration_seconds,
            "participants": self.participants,
            "start_time": self.start_time,
            "assets": assets,
            "slides": {
                "available": slides.get("available", False),
                "count": slides.get("count", 0),
                "format": slides.get("format"),
                "note": f"timeline source: {slides.get('source') or 'unknown'}"
                if slides.get("available") else "No slide timeline found",
            },
            "strategy": self.strategy,
            "estimated_output_mb": self.estimated_output_mb,
            "warnings": self.warnings,
        }
        if internal:
            out["asset_root"] = self.asset_root
            out["timeline_base_url"] = self.timeline_base_url
            out["asset_roots"] = self.asset_roots
            out["timeline"] = {
                "source": self.timeline.source,
                "slide_hrefs": self.timeline.unique_slide_hrefs,
                "slides": [
                    {"href": s.href, "start": s.start, "end": s.end,
                     "x": s.x, "y": s.y, "width": s.width, "height": s.height}
                    for s in self.timeline.slides
                ],
                "shapes": [
                    {"start": s.start, "end": s.end, "xml": s.xml}
                    for s in self.timeline.shapes[:4000]
                ],
            }
        return out


# ---------------------------------------------------------------------------
# Candidate asset locations (BBB 2.0 → 3.x naming variants).
CANDIDATES = {
    "direct_video": [
        "video/mp4/{id}.mp4",
        "video/webm/{id}.webm",
        "video/{id}.mp4",
        "video/merged.mp4",
    ],
    "webcam": [
        "video/webcams.webm",     # BBB 2.6+/3.x (all webcams composited; audio usually embedded)
        "video/webcams.mp4",
        "video/webcam.webm",      # BBB 2.0/2.3
        "video/webcam.mp4",
    ],
    "screenshare": [
        "video/screenshare.webm",
        "deskshare/deskshare.webm",  # BBB 2.0
    ],
    "audio": [
        "audio/audio.webm",       # BBB 3.x
        "audio/audio_only.webm",  # BBB 2.3
        "audio/audio.ogg",        # BBB 2.0
        "audio/audio_only.ogg",
        "audio/audio.wav",
    ],
}

STRATEGY_LABELS = {
    "direct": "Direct remux of an existing video",
    "streams": "Merge media streams (webcam/screenshare + audio)",
    "reconstruct": "Reconstruct video from slides + webcam + audio",
    "audio_only": "Audio-only export",
    "unsupported": "Unsupported — required media not accessible",
}


class RecordingInspector:
    def __init__(self, settings: Settings, fetcher: SafeFetcher | None = None) -> None:
        self.settings = settings
        self._fetcher = fetcher or SafeFetcher(settings)
        self._asset_roots_tried: list[str] = []

    # -- probing helpers ---------------------------------------------------
    def _probe(self, roots: list[str], rels: list[str], expect_ct: tuple[str, ...]) -> ProbeResult:
        for rel in rels:
            for root in roots:
                url = f"{root.rstrip('/')}/{rel.lstrip('/')}"
                try:
                    status, ct, length = self._fetcher.head(url)
                except SourceError as exc:
                    if exc.code in ("SOURCE_TIMEOUT", "TLS_ERROR"):
                        raise
                    continue
                if status == 200 and not soft404(ct, expect_ct):
                    return ProbeResult(available=True, url=url, content_type=ct.split(";")[0], size_bytes=length)
        return ProbeResult(available=False)

    def _fetch_xml(self, roots: list[str], rel: str):
        for root in roots:
            url = f"{root.rstrip('/')}/{rel.lstrip('/')}"
            try:
                res: FetchResult = self._fetcher.fetch(url, max_bytes=8 * 1024 * 1024)
            except SourceError:
                continue
            if res.looks_like_html:
                continue
            try:
                return url, res.data, None
            except Exception:  # pragma: no cover
                continue
        return None, None, None

    # -- main entry ----------------------------------------------------------
    def inspect(self, parsed: ParsedRecordingUrl) -> Inspection:
        roots = parsed.asset_roots
        insp = Inspection(
            url=parsed.normalized_url,
            server_host=parsed.server_host,
            meeting_id=parsed.meeting_id,
            playback_version=parsed.playback_version,
            asset_root="",
            asset_roots=list(roots),
        )
        self._asset_roots_tried = list(roots)

        # 1) metadata.xml — also selects the working asset root.
        meta_url, meta_data, _ = self._fetch_xml(roots, "metadata.xml")
        if meta_data:
            try:
                meta = parse_metadata_xml(meta_data)
                insp.title = meta["title"]
                insp.duration_seconds = meta["duration_seconds"]
                insp.start_time = meta["start_time"]
                insp.participants = meta["participants"]
                insp.asset_root = meta_url.rsplit("/", 1)[0]
            except ValueError as exc:
                insp.warnings.append(f"metadata.xml could not be parsed: {exc}")
        else:
            insp.warnings.append(
                "metadata.xml is not accessible on this server; relying on media probing only."
            )
        if insp.asset_root:
            roots = [insp.asset_root] + [r for r in roots if r != insp.asset_root]

        # 2) probe media candidates (content-type validated).
        insp.direct_video = self._probe(roots, CANDIDATES["direct_video"], MEDIA_CT)
        insp.webcam = self._probe(roots, CANDIDATES["webcam"], MEDIA_CT)
        insp.screenshare = self._probe(roots, CANDIDATES["screenshare"], MEDIA_CT)
        insp.audio = self._probe(roots, CANDIDATES["audio"], MEDIA_CT)

        # 3) slide timeline: shapes.svg first (it also carries annotations),
        #    fallback slides_new.xml. Relative slide hrefs resolve against the
        #    directory of the file they were parsed from.
        timeline = Timeline()
        timeline_base = ""
        _, shapes_data, shapes_url = self._fetch_xml(roots, "shapes.svg")
        if shapes_data:
            try:
                timeline = parse_shapes_svg(shapes_data)
                spans = extract_shape_spans(shapes_data)
                insp.has_annotations = bool(spans)
                timeline.shapes = spans
                if shapes_url:
                    timeline_base = shapes_url.rsplit("/", 1)[0]
            except ValueError as exc:
                insp.warnings.append(f"shapes.svg could not be parsed: {exc}")
        if not timeline.slides:
            _, slides_data, slides_url = self._fetch_xml(roots, "slides_new.xml")
            if slides_data:
                try:
                    timeline = parse_slides_new_xml(slides_data)
                    if slides_url:
                        timeline_base = slides_url.rsplit("/", 1)[0]
                except ValueError as exc:
                    insp.warnings.append(f"slides_new.xml could not be parsed: {exc}")
        insp.timeline = timeline
        insp.timeline_base_url = timeline_base or insp.asset_root

        if not (insp.direct_video.available or insp.webcam.available or insp.screenshare.available
                or insp.audio.available or timeline.slides):
            raise SourceError(
                ASSETS_MISSING,
                "No accessible recording media was found on this server. The playback page exists, "
                "but its media files (audio/webcam/slides) are not reachable — the server may "
                "restrict access or the recording may be unpublished.",
                details={"asset_roots_tried": roots},
            )

        if insp.duration_seconds <= 0:
            # Fall back to the last slide out point as a rough duration.
            if timeline.slides:
                insp.duration_seconds = max(s.end for s in timeline.slides)
                insp.warnings.append(
                    "Duration estimated from the slide timeline (metadata.xml lacked duration)."
                )
        if insp.duration_seconds > self.settings.max_recording_hours * 3600:
            raise SourceError(
                SOURCE_ERROR,
                f"Recording duration ({insp.duration_seconds / 3600:.1f} h) exceeds the configured "
                f"maximum of {self.settings.max_recording_hours:g} h.",
            )

        self._select_strategy(insp)
        return insp

    # -- strategy ------------------------------------------------------------
    def _select_strategy(self, insp: Inspection) -> None:
        has_video = insp.direct_video.available
        has_cam = insp.webcam.available or insp.screenshare.available
        has_audio = insp.audio.available or (insp.webcam.available and True)  # webcams.* embeds audio
        has_slides = bool(insp.timeline.slides)

        limitations: list[str] = []
        if has_slides:
            limitations.append(
                "Slide pan/zoom (panzooms.xml) and the live cursor are not animated in the output; "
                "each slide is shown fitted to the canvas for its full interval."
            )
            if insp.has_annotations:
                limitations.append(
                    "Whiteboard annotations are composited per slide interval (annotation-level "
                    "timing is approximated)."
                )

        if has_video:
            strategy = "direct"
            explanation = (
                "A complete video file is published alongside the playback page. It will be "
                "remuxed (or transcoded when its codecs are not MP4-compatible) into the "
                "requested format without recompositing."
            )
            limitations = []
        elif has_slides and (has_cam or insp.audio.available):
            strategy = "reconstruct"
            explanation = (
                "No ready-made video exists. The converter will rebuild the recording: presentation "
                "slides are rasterized and placed on a 1600x900 canvas according to their timeline, "
                "the webcam stream (when available) is overlaid as a picture-in-picture, and audio is "
                "synchronized and encoded into the requested format."
            )
        elif has_cam:
            strategy = "streams"
            explanation = (
                "No ready-made video and no slide data. The webcam/screenshare stream and the audio "
                "track will be synchronized by their timestamps and combined into a single video."
            )
            if insp.webcam.available and insp.webcam.content_type and "webm" in insp.webcam.content_type:
                limitations.append("Webcam video is VP8/VP9 in WebM and will be transcoded to H.264 for MP4 output.")
        elif insp.audio.available:
            strategy = "audio_only"
            explanation = (
                "Only an audio track is published. MP3 exports the audio directly; MP4 produces a "
                "video with a static title card over the audio."
            )
        else:
            strategy = "unsupported"
            explanation = (
                "None of the required media assets (video, webcam, audio, slides) are accessible. "
                "The playback page may be an interactive-only view protected by the server."
            )

        insp.strategy = {
            "id": strategy,
            "label": STRATEGY_LABELS[strategy],
            "supported": strategy != "unsupported",
            "explanation": explanation,
            "limitations": limitations,
        }

        # rough output size estimates (very rough; refined after download)
        d = max(insp.duration_seconds, 1.0)
        if strategy == "direct" and insp.direct_video.size_bytes:
            est_video = insp.direct_video.size_bytes / 1e6
        elif strategy in ("reconstruct", "streams"):
            src = insp.webcam.size_bytes or insp.screenshare.size_bytes or 0
            est_video = max(src / 1e6, d * 0.12)
        else:
            est_video = 0.0
        est_audio = d * 0.016  # ~128 kbps
        insp.estimated_output_mb = {
            "mp4": round(est_video + est_audio, 1) if strategy != "audio_only" else round(d * 0.0012 + est_audio * 0.75, 1),
            "webm": round((est_video + est_audio) * 0.8, 1) if strategy != "audio_only" else round(d * 0.001, 1),
            "mp3": round(d * 0.015, 1),
        }
        if strategy == "unsupported":
            insp.estimated_output_mb = {}
