"""Conversion pipeline: downloads assets, then rebuilds/remuxes media with FFmpeg.

Strategies (selected during inspection, persisted on the job):
- direct        : an existing complete video is remuxed/transcoded
- streams       : webcam/screenshare + audio merged by timestamps
- reconstruct   : slides + annotations + webcam PiP + audio rebuilt on a canvas
- audio_only    : audio extraction (mp3) or static-image video (mp4)

Real progress is reported at every stage: download bytes, per-slide rendering,
and FFmpeg `out_time` for every encode step.
"""

from __future__ import annotations

import re
import shutil
from datetime import timedelta
from pathlib import Path

from app.config import Settings, get_settings
from app.db import session as db_session
from app.errors import (
    ASSETS_MISSING,
    CANCELED,
    DOWNLOAD_TOO_LARGE,
    FFMPEG_FAILED,
    JOB_NOT_FOUND,
    PROCESSING_CODES,
    QUOTA_EXCEEDED,
    UNSUPPORTED_RECORDING,
    ProcessingError,
    SourceError,
)
from app.media import ffmpeg as ff
from app.media.render import (
    build_slide_video,
    composite_slide_with_shapes,
    extract_shapes_viewbox,
    merge_intervals,
    rasterize_slide,
)
from app.models import ConversionJob, utcnow
from app.security.fetcher import SafeFetcher

# progress checkpoints
P_DOWNLOAD = (0.0, 0.35)
P_PROBE = (0.35, 0.40)
P_ENCODE = (0.40, 0.90)


def _get_job(db, job_id: str) -> ConversionJob:  # noqa: ANN001
    job = db.get(ConversionJob, job_id)
    if job is None:
        raise ProcessingError(JOB_NOT_FOUND, f"Job {job_id} does not exist.")
    return job


def _update(db, job: ConversionJob, **fields) -> None:  # noqa: ANN001
    for k, v in fields.items():
        setattr(job, k, v)
    db.add(job)
    db.commit()


def _check_storage(settings: Settings, needed_bytes: int) -> None:
    usage = shutil.disk_usage(settings.data_dir)
    if usage.free - needed_bytes < settings.min_free_disk_gb * 1024**3:
        raise ProcessingError(
            QUOTA_EXCEEDED,
            f"Not enough free disk space (need ~{needed_bytes / 1e9:.1f} GB, "
            f"free {usage.free / 1e9:.1f} GB).",
        )


def _safe_name(href: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", href)[-120:]


def _ext_of(info: dict | None) -> str:
    if not info:
        return ".bin"
    url = (info.get("url") or "").lower()
    ct = (info.get("content_type") or "").lower()
    if url.endswith((".webm", ".mp4", ".ogg", ".wav", ".m4a", ".mp3")):
        return "." + url.rsplit(".", 1)[1]
    if "webm" in ct:
        return ".webm"
    if "mp4" in ct:
        return ".mp4"
    if "ogg" in ct:
        return ".ogg"
    return ".bin"


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Pipeline:
    def __init__(self, job_id: str, settings: Settings | None = None) -> None:
        self.job_id = job_id
        self.settings = settings or get_settings()
        self.work: Path = self.settings.work_dir / job_id
        self._fetcher: SafeFetcher | None = None

    # -- plumbing -----------------------------------------------------------
    def _canceled(self) -> bool:
        db = db_session()
        try:
            job = db.get(ConversionJob, self.job_id)
            return bool(job and job.canceled)
        finally:
            db.close()

    @property
    def fetcher(self) -> SafeFetcher:
        if self._fetcher is None:
            self._fetcher = SafeFetcher(self.settings)
        return self._fetcher

    def _raise_if_canceled(self) -> None:
        if self._canceled():
            raise ProcessingError(CANCELED, "The job was canceled by the user.",
                                  details={"canceled": True})

    # -- download stage -------------------------------------------------------
    def _select_download_assets(self, strategy: str, assets: dict) -> list[tuple[str, dict]]:
        wanted: list[tuple[str, dict]] = []
        if strategy == "direct":
            if assets.get("direct_video", {}).get("available"):
                wanted.append(("video", assets["direct_video"]))
        elif strategy == "streams":
            for key in ("webcam", "screenshare"):
                if assets.get(key, {}).get("available"):
                    wanted.append(("video", assets[key]))
                    break
            if assets.get("audio", {}).get("available"):
                wanted.append(("audio", assets["audio"]))
        elif strategy == "reconstruct":
            for key in ("webcam", "screenshare"):
                if assets.get(key, {}).get("available"):
                    wanted.append(("video", assets[key]))
                    break
            if assets.get("audio", {}).get("available"):
                wanted.append(("audio", assets["audio"]))
        elif strategy == "audio_only":
            if assets.get("audio", {}).get("available"):
                wanted.append(("audio", assets["audio"]))
            elif assets.get("webcam", {}).get("available"):
                wanted.append(("audio", assets["webcam"]))
            elif assets.get("screenshare", {}).get("available"):
                wanted.append(("audio", assets["screenshare"]))
        return wanted

    def _download(self, db, job: ConversionJob, assets: dict) -> dict[str, Path]:  # noqa: ANN001
        self.work.mkdir(parents=True, exist_ok=True)
        wanted = self._select_download_assets(job.strategy, assets)
        if not wanted:
            raise ProcessingError(ASSETS_MISSING,
                                  "No downloadable media assets for the selected strategy.")

        # size guard (declared sizes only; slides checked separately)
        known = sum((a.get("size_bytes") or 0) for _, a in wanted)
        if known > self.settings.max_total_assets_bytes:
            raise ProcessingError(
                DOWNLOAD_TOO_LARGE,
                f"Recording assets total ~{known / 1e9:.1f} GB which exceeds the "
                f"{self.settings.max_total_assets_bytes / 1e9:.1f} GB processing limit.",
            )
        _check_storage(self.settings, max(known * 2, 512 * 1024 * 1024))

        paths: dict[str, Path] = {}
        sizes: dict[str, int | None] = {}
        for _, info in wanted:
            url = info["url"]
            if url not in sizes:
                try:
                    _, _, ln = self.fetcher.head(url)
                    sizes[url] = ln
                except SourceError:
                    sizes[url] = None

        grand_total = sum(s for s in sizes.values() if s)
        done_bytes = 0

        for key, info in wanted:
            self._raise_if_canceled()
            url = info["url"]
            dest = self.work / (key + _ext_of(info))
            if dest.exists() and dest.stat().st_size > 0:
                paths[key] = dest
                continue
            size = sizes.get(url)

            def on_bytes(written: int, total: int | None) -> None:
                if grand_total:
                    frac = (done_bytes + written) / grand_total
                else:
                    frac = 0.5
                self._progress(db, job,
                               P_DOWNLOAD[0] + (P_DOWNLOAD[1] - P_DOWNLOAD[0]) * frac,
                               f"Downloading {key}")

            try:
                self.fetcher.download_to_file(
                    url, dest,
                    max_bytes=self.settings.max_asset_bytes,
                    progress=on_bytes,
                    should_cancel=self._raise_if_canceled,
                )
            except SourceError as exc:
                if exc.details.get("canceled"):
                    raise ProcessingError(CANCELED, "Download canceled.",
                                          details={"canceled": True}) from exc
                raise
            done_bytes += size or (dest.stat().st_size if dest.exists() else 0)
            paths[key] = dest
        return paths

    # -- encode stages --------------------------------------------------------
    def _encode_direct(self, db, job: ConversionJob, src: Path, out: Path) -> None:  # noqa: ANN001
        streams = ff.probe_streams(src)
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        fmt = job.format
        duration = ff.probe_duration(src)

        if fmt == "mp3":
            self._encode_audio(src, out, duration, db, job)
            return

        if fmt == "mp4":
            video_ok = bool(v and v.get("codec_name") in ("h264",) and _container_ok(src, "mp4"))
            audio_ok = bool(a and a.get("codec_name") in ("aac", "mp3") and _container_ok(src, "mp4"))
            if video_ok and audio_ok:
                args = ["-i", str(src), "-c", "copy", "-movflags", "+faststart", str(out)]
                label = "Remuxing to MP4 (stream copy)"
            elif video_ok:
                args = ["-i", str(src), "-map", "0:v", "-map", "0:a?",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart", str(out)]
                label = "Transcoding audio to AAC"
            else:
                args = self._transcode_args(src, out, fmt, has_audio=bool(a))
                label = "Transcoding to H.264/AAC MP4"
        else:  # webm
            video_ok = bool(v and v.get("codec_name") in ("vp8", "vp9") and _container_ok(src, "webm"))
            audio_ok = bool(a and a.get("codec_name") in ("vorbis", "opus") and _container_ok(src, "webm"))
            if video_ok and audio_ok:
                args = ["-i", str(src), "-c", "copy", str(out)]
                label = "Remuxing to WebM (stream copy)"
            else:
                args = self._transcode_args(src, out, fmt, has_audio=bool(a))
                label = "Transcoding to WebM (VP9)"
        self._run_encode(args, duration, label, db, job)

    def _transcode_args(self, src: Path, out: Path, fmt: str, has_audio: bool) -> list[str]:
        if fmt == "mp4":
            args = ["-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p"]
            args += ["-c:a", "aac", "-b:a", "128k"] if has_audio else ["-an"]
            args += ["-movflags", "+faststart"]
        else:
            args = ["-i", str(src), "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "5",
                    "-row-mt", "1", "-crf", "34", "-b:v", "0", "-pix_fmt", "yuv420p"]
            args += ["-c:a", "libopus", "-b:a", "128k"] if has_audio else ["-an"]
        args.append(str(out))
        return args

    def _encode_streams(self, db, job: ConversionJob, video: Path | None,
                        audio: Path | None, out: Path) -> None:  # noqa: ANN001
        fmt = job.format
        if video is None:
            if audio is None:
                raise ProcessingError(ASSETS_MISSING, "No media available to encode.")
            if fmt == "mp3":
                self._encode_audio(audio, out, ff.probe_duration(audio), db, job)
                return
            card = self._title_card(job)
            dur = ff.probe_duration(audio)
            args = self._static_video_args(card, audio, fmt, out)
            self._run_encode(args, dur, "Building video with static title card", db, job)
            return

        v_dur = ff.probe_duration(video)
        if fmt == "mp3":
            self._encode_audio(video, out, v_dur, db, job)
            return

        a_dur = ff.probe_duration(audio) if audio else (
            v_dur if ff.has_stream(video, "audio") else 0.0
        )
        total = max(v_dur, a_dur, 0.5)

        # Build inputs; guarantee an audio stream exists.
        inputs: list[Path] = [video]
        if audio:
            inputs.append(audio)
        audio_src_idx: int | None = 1 if audio else (0 if ff.has_stream(video, "audio") else None)
        if audio_src_idx is None:
            inputs.append(Path("anullsrc"))  # resolved via lavfi below
            audio_src_idx = len(inputs) - 1

        vf_pad = (f"tpad=stop_mode=clone:stop_duration={max(0.0, total - v_dur + 0.5):.3f}"
                  if v_dur < total else "null")
        if audio_src_idx is not None and inputs[audio_src_idx].name == "anullsrc":
            af_pad = "anull"
        elif a_dur < total:
            af_pad = f"apad=pad_dur={max(0.0, total - a_dur + 0.5):.3f}"
        else:
            af_pad = "anull"

        pre: list[str] = []
        ai = audio_src_idx
        if inputs[ai].name == "anullsrc":
            pre = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            # shift: lavfi input is appended AFTER regular inputs
            ai = len(inputs) - 1

        args: list[str] = []
        for p in inputs:
            if p.name == "anullsrc":
                continue
            args += ["-i", str(p)]
        args = pre + args if pre else args
        # Recompute audio index: lavfi input appended last.
        if inputs[audio_src_idx].name == "anullsrc":
            ai = len(inputs) - 1

        filter_complex = f"[0:v]{vf_pad},format=yuv420p[v];[{ai}:a]{af_pad}[a]"

        if fmt == "mp4":
            args += ["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                     "-c:a", "aac", "-b:a", "128k",
                     "-t", f"{total:.3f}", "-movflags", "+faststart"]
            label = "Merging streams into MP4"
        else:
            streams = ff.probe_streams(video)
            vcodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "video"), "")
            acodec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), "")
            can_copy = (
                vcodec in ("vp8", "vp9")
                and audio is None
                and acodec in ("vorbis", "opus")
                and v_dur >= a_dur - 0.5
            )
            if can_copy:
                args = ["-i", str(video), "-c", "copy"]
                label = "Remuxing to WebM (stream copy)"
            else:
                args += ["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]",
                         "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "5",
                         "-row-mt", "1", "-crf", "34", "-b:v", "0",
                         "-c:a", "libopus", "-b:a", "128k", "-t", f"{total:.3f}"]
                label = "Transcoding to WebM (VP9/Opus)"
        args.append(str(out))
        self._run_encode(args, total, label, db, job)

    def _static_video_args(self, card: Path, audio: Path, fmt: str, out: Path) -> list[str]:
        if fmt == "webm":
            return ["-loop", "1", "-i", str(card), "-i", str(audio),
                    "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "8",
                    "-crf", "36", "-b:v", "0", "-pix_fmt", "yuv420p",
                    "-c:a", "libopus", "-b:a", "128k", "-shortest", str(out)]
        return ["-loop", "1", "-i", str(card), "-i", str(audio),
                "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
                "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart", str(out)]

    # -- reconstruction ---------------------------------------------------------
    def _encode_reconstruct(self, db, job: ConversionJob, paths: dict, out: Path) -> None:  # noqa: ANN001
        # MP3 never needs slides or video: extract audio directly from the
        # downloaded source (separate audio asset, or the webcam's audio track).
        if job.format == "mp3":
            src = paths.get("audio") or paths.get("video")
            if src is None:
                raise ProcessingError(ASSETS_MISSING, "No audio source available for MP3 export.")
            self._encode_audio(src, out, ff.probe_duration(src), db, job)
            return

        assets = job.assets_json or {}
        timeline = assets.get("timeline") or {}
        # Slide hrefs are relative to the file they were parsed from (shapes.svg
        # or slides_new.xml); fall back to the discovered asset root.
        slide_base = assets.get("timeline_base_url") or assets.get("asset_root", "")
        slides_dir = self.work / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        webcam = paths.get("video")
        audio = paths.get("audio")

        duration = job.duration_seconds or 0.0
        # The probed media duration is authoritative (metadata start/end often
        # includes pre-roll that was never published).
        if webcam:
            media_dur = ff.probe_duration(webcam)
            duration = min(duration, media_dur) if duration > 0 else media_dur
        if audio:
            media_dur = ff.probe_duration(audio)
            duration = min(duration, media_dur) if duration > 0 else media_dur
        if duration <= 0:
            raise ProcessingError(FFMPEG_FAILED, "Could not determine the recording duration.")

        # ---- stage 1: fetch + rasterize unique slides ------------------------
        hrefs: list[str] = list(timeline.get("slide_hrefs", []))
        if not hrefs:
            raise ProcessingError(ASSETS_MISSING, "Slide timeline is empty.")
        slide_pngs: dict[str, Path] = {}
        shapes = _spans_from_json(timeline)
        total = max(1, len(hrefs))
        for idx, href in enumerate(hrefs):
            self._raise_if_canceled()
            local = slides_dir / ("raw_" + _safe_name(href))
            if not local.exists():
                # Try the timeline base first, then the metadata asset root,
                # then every known asset root (servers expose different trees).
                candidates: list[str] = []
                if href.startswith("http"):
                    candidates = [href]
                else:
                    for base in filter(None, [slide_base, assets.get("asset_root", ""),
                                              *assets.get("asset_roots", [])]):
                        candidates.append(f"{base.rstrip('/')}/{href.lstrip('/')}")
                last_err: Exception | None = None
                for url in candidates:
                    try:
                        self.fetcher.download_to_file(url, local, max_bytes=64 * 1024 * 1024,
                                                      should_cancel=self._raise_if_canceled)
                        last_err = None
                        break
                    except SourceError as exc:
                        last_err = exc
                        continue
                if last_err is not None or not local.exists():
                    raise ProcessingError(
                        ASSETS_MISSING, f"Slide asset could not be downloaded: {href} ({last_err})")
            png = slides_dir / (_safe_name(href) + ".png")
            if not png.exists():
                rasterize_slide(local, png)
                if shapes:
                    spans = [s for s in shapes if _annotation_in_slide(s, timeline, href)]
                    if spans:
                        try:
                            shapes_svg_path = slides_dir / "shapes.svg"
                            if not shapes_svg_path.exists():
                                self.fetcher.download_to_file(
                                    f"{slide_base.rstrip('/')}/shapes.svg", shapes_svg_path,
                                    max_bytes=64 * 1024 * 1024,
                                    should_cancel=self._raise_if_canceled)
                            vb = extract_shapes_viewbox(shapes_svg_path)
                            comp = png.with_suffix(".ann.png")
                            composite_slide_with_shapes(png, spans, comp, vb)
                            shutil.move(comp, png)
                        except (ProcessingError, SourceError):
                            pass  # keep the base slide
            slide_pngs[href] = png
            self._progress(db, job, P_ENCODE[0] + 0.05 * (idx + 1) / total,
                           f"Rendering slides ({idx + 1}/{total})")

        intervals = merge_intervals_from_job(timeline, duration)

        # ---- stage 2: slide timeline video ------------------------------------
        slides_video = self.work / "slides_only.mp4"
        build_slide_video(
            intervals, slide_pngs, slides_video, duration,
            progress=lambda f: self._progress(db, job, 0.45 + 0.20 * f,
                                              "Building slide timeline video"),
            should_cancel=self._raise_if_canceled,
        )

        # ---- stage 3: webcam PiP + audio mux ----------------------------------
        if webcam is None and audio is None:
            self._finalize_slides_only(db, job, slides_video, out, duration)
            return

        v_dur = ff.probe_duration(slides_video)
        a_dur = ff.probe_duration(audio) if audio else (
            ff.probe_duration(webcam) if webcam else v_dur
        )
        total_dur = max(v_dur, a_dur, duration, 0.5)

        if job.format == "mp3":
            src = audio or webcam
            self._encode_audio(src, out, total_dur, db, job)
            return

        # pad the slide video to cover the full duration
        if v_dur < total_dur:
            padded = self.work / "slides_padded.mp4"
            ff.FfmpegRunner.run(
                ["-i", str(slides_video), "-vf",
                 f"tpad=stop_mode=clone:stop_duration={total_dur - v_dur + 0.5:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", str(padded)],
                should_cancel=self._raise_if_canceled, timeout_s=1800,
            )
            slides_video = padded

        # inputs: [0]=slides [1]=webcam? [n]=audio?
        args: list[str] = ["-i", str(slides_video)]
        audio_idx: int | None = None
        if webcam and job.include_webcam_pip:
            args += ["-i", str(webcam)]
        if audio:
            args += ["-i", str(audio)]
            audio_idx = len(args) // 2 - 1
        elif webcam and ff.has_stream(webcam, "audio"):
            audio_idx = 1
        if audio_idx is None:
            args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            audio_idx = len(args) // 2 - 1

        if webcam and job.include_webcam_pip:
            filter_complex = (
                "[1:v]scale=400:300:force_original_aspect_ratio=decrease,"
                "pad=400:300:(ow-iw)/2:(oh-ih)/2,format=yuv420p[pip];"
                "[0:v][pip]overlay=x=W-w-24:y=H-h-24:shortest=0[v]"
            )
        else:
            filter_complex = "[0:v]format=yuv420p[v]"

        out_is_webm = job.format == "webm"
        codec_v = (["-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "5", "-row-mt", "1",
                    "-crf", "33", "-b:v", "0"] if out_is_webm
                   else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
        codec_a = (["-c:a", "libopus", "-b:a", "128k"] if out_is_webm
                   else ["-c:a", "aac", "-b:a", "128k"])

        args += [
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", f"{audio_idx}:a",
            *codec_v, *codec_a, "-pix_fmt", "yuv420p",
            "-t", f"{total_dur:.3f}",
            *(["-movflags", "+faststart"] if not out_is_webm else []),
            str(out),
        ]
        self._run_encode(args, total_dur, "Compositing slides, webcam and audio", db, job)

    def _finalize_slides_only(self, db, job: ConversionJob, slides_video: Path, out: Path,
                              duration: float) -> None:  # noqa: ANN001
        if job.format == "mp4":
            shutil.move(slides_video, out)
            return
        args = self._transcode_args(slides_video, out, job.format, has_audio=False)
        self._run_encode(args, duration, "Transcoding slide video", db, job)

    # -- audio helper ----------------------------------------------------------
    def _encode_audio(self, src: Path, out: Path, duration: float, db, job: ConversionJob) -> None:  # noqa: ANN001
        self._run_encode(
            ["-i", str(src), "-vn", "-c:a", "libmp3lame", "-q:a", "4", str(out)],
            duration, "Extracting audio to MP3", db, job,
        )

    def _title_card(self, job: ConversionJob) -> Path:
        card = self.work / "card.png"
        if card.exists():
            return card
        title = (job.title or "BigBlueButton Recording").replace("\\", " ").replace(":", " ")[:80]
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">'
            '<rect width="1600" height="900" fill="#101318"/>'
            f'<text x="800" y="430" font-family="DejaVu Sans" font-size="52" fill="#e6e8ee" '
            f'text-anchor="middle">{_xml_escape(title)}</text>'
            '<text x="800" y="500" font-family="DejaVu Sans" font-size="30" fill="#8b90a0" '
            'text-anchor="middle">BigBlueButton Recording Converter</text></svg>'
        )
        import cairosvg

        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(card))
        return card

    def _run_encode(self, args: list[str], duration: float, label: str, db, job: ConversionJob) -> None:  # noqa: ANN001
        span = P_ENCODE[1] - P_ENCODE[0]

        def on_prog(f: float) -> None:
            self._progress(db, job, P_ENCODE[0] + span * min(1.0, f), label)

        self._raise_if_canceled()
        ff.FfmpegRunner.run(
            args,
            duration_hint=duration if duration > 0 else None,
            progress=on_prog,
            should_cancel=self._raise_if_canceled,
            timeout_s=self.settings.ffmpeg_timeout_s,
            cwd=self.work,
        )

    def _progress(self, db, job: ConversionJob, overall: float, detail: str = "") -> None:  # noqa: ANN001
        _update(db, job, progress=min(0.999, max(0.0, overall)),
                progress_detail=detail[:500])

    # -- main entry --------------------------------------------------------------
    def execute(self) -> None:
        db = db_session()
        job = _get_job(db, self.job_id)
        try:
            if job.status == "canceled":
                return
            _update(db, job, status="running", stage="downloading",
                    started_at=utcnow(), progress=0.0)
            assets = (job.assets_json or {}).get("assets", {})
            paths = self._download(db, job, assets)

            _update(db, job, stage="probing")
            self._raise_if_canceled()
            self._progress(db, job, P_PROBE[0], "Analyzing media streams")

            _update(db, job, stage="encoding")
            out_name = f"{job.id}.{job.format}"
            out_path = self.settings.output_dir / out_name
            self.settings.output_dir.mkdir(parents=True, exist_ok=True)

            if job.strategy == "direct":
                self._encode_direct(db, job, paths["video"], out_path)
            elif job.strategy == "streams":
                self._encode_streams(db, job, paths.get("video"), paths.get("audio"), out_path)
            elif job.strategy == "reconstruct":
                self._encode_reconstruct(db, job, paths, out_path)
            elif job.strategy == "audio_only":
                self._encode_streams(db, job, None, paths.get("audio"), out_path)
            else:
                raise ProcessingError(UNSUPPORTED_RECORDING, f"Unknown strategy '{job.strategy}'.")

            if not out_path.exists() or out_path.stat().st_size < 1024:
                raise ProcessingError(FFMPEG_FAILED,
                                      "The encoder did not produce a valid output file.")

            _update(db, job, stage="finalizing")
            self._raise_if_canceled()
            out_dur = ff.probe_duration(out_path) or job.duration_seconds
            _update(
                db, job,
                status="completed", stage="done", progress=1.0,
                output_filename=out_name,
                output_size=out_path.stat().st_size,
                output_duration=round(out_dur, 3),
                finished_at=utcnow(),
                expires_at=utcnow() + timedelta(hours=self.settings.output_ttl_hours),
                progress_detail="Completed",
            )
            shutil.rmtree(self.work, ignore_errors=True)
        except Exception as exc:
            code = getattr(exc, "code", "INTERNAL_ERROR")
            msg = getattr(exc, "message", str(exc))
            canceled = code == CANCELED or bool((getattr(exc, "details", {}) or {}).get("canceled"))
            try:
                job2 = _get_job(db, self.job_id)
                _update(
                    db, job2,
                    status="canceled" if canceled else "failed",
                    stage="done",
                    error_code=CANCELED if canceled else code,
                    error_message=msg,
                    finished_at=utcnow(),
                )
            except Exception:  # pragma: no cover
                pass
            shutil.rmtree(self.work, ignore_errors=True)
        finally:
            db.close()
            if self._fetcher:
                self._fetcher.close()


def _container_ok(path: Path, container: str) -> bool:
    return path.suffix.lower() == f".{container}"


def _spans_from_json(timeline: dict) -> list:
    from app.bbb.parsing import ShapeSpan

    return [ShapeSpan(start=s["start"], end=s["end"], xml=s["xml"])
            for s in timeline.get("shapes", [])]


def _annotation_in_slide(span, timeline: dict, href: str) -> bool:  # noqa: ANN001
    """Approximate mapping: annotation belongs to the slide interval it starts in."""
    slides = timeline.get("slides", [])
    for s in slides:
        if s["href"] == href and s["start"] - 0.01 <= span.start < s["end"]:
            return True
    return False


def merge_intervals_from_job(timeline: dict, duration: float):
    from app.bbb.parsing import SlideInterval, Timeline

    tl = Timeline()
    tl.slides = [
        SlideInterval(href=s["href"], start=s["start"], end=s["end"],
                      x=s.get("x", 0.0), y=s.get("y", 0.0),
                      width=s.get("width"), height=s.get("height"))
        for s in timeline.get("slides", [])
    ]
    return merge_intervals(tl, duration)


def run_job(job_id: str) -> None:
    """Entry point used by both the inline worker and Celery."""
    Pipeline(job_id).execute()
