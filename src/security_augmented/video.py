"""Timestamp-first ingestion, sampling and replay using FFmpeg."""

from bisect import bisect_left
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
from math import ceil, floor
from pathlib import Path
import re
import subprocess
import tempfile

from .contracts import (
    SCHEMA_VERSION, US_PER_SECOND, ClipFrame, ClipInspection, FrameEvidence,
    Inspection, Interval, Video, VideoError,
)

_SELECTION_POLICY = "first_at_or_after_within_interval"
_PIXEL_FORMAT = "rgb24"
_SHOWINFO_BASE = re.compile(rb"config in time_base: (\d+/\d+)")
_SHOWINFO_FRAME = re.compile(
    rb"\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:.*?\bs:(\d+)x(\d+)"
)


def _run(*args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, input=input_bytes, capture_output=True, check=True)
    except OSError as exc:
        raise VideoError(f"Unable to run {args[0]}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise VideoError(f"{args[0]} failed: {detail}") from exc
    return result


def _version(tool: str) -> str:
    return _run(tool, "-version").stdout.decode().splitlines()[0]


def _source_hash(path: Path) -> str:
    try:
        if not path.is_file():
            raise VideoError(f"Source is not a file: {path}")
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    except OSError as exc:
        raise VideoError(f"Unable to read source: {path}") from exc


def _id(kind: str, *values: object) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return f"{kind}-{hashlib.sha256(payload).hexdigest()}"


def ingest(path: Path) -> Video:
    """Index presentation-order PTS on the first video stream."""
    video, _ = _probe_source(path)
    return video


def _frame_duration(frame: dict) -> int | None:
    duration = frame.get("duration", frame.get("pkt_duration"))
    return int(duration) if duration is not None else None


def _probe_source(
    path: Path, *, require_clip: bool = False,
) -> tuple[Video, tuple[int | None, ...]]:
    try:
        source = Path(path).resolve()
    except (OSError, RuntimeError) as exc:
        raise VideoError(f"Unable to resolve source: {path}") from exc
    digest = _source_hash(source)
    probe = _run(
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-show_frames", "-show_format", "-show_entries",
        "stream=index,time_base,width,height,codec_name:frame=pts,duration,pkt_duration:"
        "format=format_name,nb_streams",
        "-of", "json", str(source),
    )
    if probe.stderr:
        raise VideoError(probe.stderr.decode(errors="replace").strip())
    try:
        data = json.loads(probe.stdout)
        stream, = data["streams"]
        frames = data["frames"]
        points = tuple(int(frame["pts"]) for frame in frames)
        first_pts = points[0]
        time_base = Fraction(stream["time_base"])
        durations = tuple(map(_frame_duration, frames))
        final_duration = durations[-1]
        stream_index = int(stream["index"])
        width, height = int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise VideoError("Source lacks usable frame PTS, stream metadata or final frame duration") from exc
    if (final_duration is None or min(time_base, final_duration, width, height) <= 0
            or any(left > right for left, right in zip(points, points[1:]))):
        raise VideoError("Source has invalid duration, dimensions or presentation timestamps")
    if require_clip and (
        stream.get("codec_name") != "ffv1" or time_base != Fraction(1, 1000)
        or data.get("format", {}).get("format_name") != "matroska,webm"
        or data.get("format", {}).get("nb_streams") != 1
    ):
        raise VideoError("Clip format must be video-only Matroska/FFV1 with a millisecond clock")
    duration_us = ceil((points[-1] - first_pts + final_duration) * time_base * US_PER_SECOND)
    video = Video(
        _id("video", digest, stream_index), digest, str(source), stream_index,
        duration_us, time_base.numerator, time_base.denominator, first_pts, points,
        final_duration, width, height, _version("ffprobe"),
    )
    validate_source(video)
    return video, durations


def validate_source(video: Video) -> Path:
    """Resolve a recorded source path and verify its original bytes."""
    if (video.schema_version != SCHEMA_VERSION
            or video.id != _id("video", video.sha256, video.stream_index)):
        raise VideoError("Invalid video identity or schema")
    path = Path(video.source_path)
    if _source_hash(path) != video.sha256:
        raise VideoError(f"Source hash mismatch: {path}")
    return path


def _source_pts(video: Video, time_us: int) -> Fraction:
    return video.first_display_pts + Fraction(time_us, US_PER_SECOND) / video.time_base


def _select(
    video: Video, interval: Interval, requests: tuple[int, ...]
) -> tuple[int | None, ...]:
    interval.validate(video.duration_us)
    if not requests or any(
        type(time) is not int or not interval.start_us <= time < interval.end_us
        for time in requests
    ):
        raise VideoError("Requested times must be integer microseconds within the interval")

    stop = bisect_left(video.frame_pts, _source_pts(video, interval.end_us))
    indices = []
    for time in requests:
        requested_pts = _source_pts(video, time)
        index = bisect_left(video.frame_pts, requested_pts, hi=stop)
        indices.append(index if index < stop else None)
    return tuple(indices)


def _decode(video: Video, indices: tuple[int, ...] | range) -> tuple[bytes, ...]:
    if not indices:
        return ()
    # Index in display order, then independently check each decoded PTS.
    if isinstance(indices, range) and indices.step == 1:
        selection = f"between(n,{indices.start},{indices.stop - 1})"
    else:
        selection = "+".join(f"eq(n,{index})" for index in indices)
    result = _run(
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-xerror",
        "-filter_threads", "1", "-copyts", "-noautorotate", "-i", video.source_path,
        "-map", f"0:{video.stream_index}", "-vf", f"select='{selection}',showinfo",
        "-frames:v", str(len(indices)), "-fps_mode", "passthrough", "-threads", "1",
        "-c:v", "rawvideo", "-pix_fmt", _PIXEL_FORMAT, "-f", "rawvideo", "pipe:1",
    )
    _verify_decoded_timestamps(video, indices, result.stderr)
    frame_size = video.width * video.height * 3
    if len(result.stdout) != frame_size * len(indices):
        raise VideoError("Unexpected decoded pixel byte count")
    return tuple(result.stdout[offset:offset + frame_size]
                 for offset in range(0, len(result.stdout), frame_size))


def _verify_decoded_timestamps(
    video: Video, indices: tuple[int, ...] | range, stderr: bytes,
) -> None:
    bases = _SHOWINFO_BASE.findall(stderr)
    timestamps = _SHOWINFO_FRAME.findall(stderr)
    expected = [(video.frame_pts[index], video.width, video.height) for index in indices]
    if (not bases or any(Fraction(base.decode()) != video.time_base for base in bases)
            or [tuple(map(int, row)) for row in timestamps] != expected):
        raise VideoError("Decoded PTS, time base or dimensions differ from the source index")


def _frame(video: Video, index: int, digest: str) -> FrameEvidence:
    pts = video.frame_pts[index]
    return FrameEvidence(
        _id("frame", video.id, index, pts, digest),
        index, pts, floor(video.time_at_pts(pts) * US_PER_SECOND), digest,
    )


def _inspection(
    video: Video, interval: Interval, requests: tuple[int, ...],
    indices: tuple[int | None, ...], frames: dict[int, FrameEvidence], version: str,
    frame_size: tuple[int, int] | None,
) -> Inspection:
    hits = sum(index is not None for index in indices)
    status = "complete" if hits == len(indices) else "partial" if hits else "empty"
    record = Inspection(
        "", video.id, interval, requests, "frames", _SELECTION_POLICY, _PIXEL_FORMAT,
        version, tuple(frames.values()),
        tuple(frames[index].id if index is not None else None for index in indices),
        status, frame_size=frame_size,
    )
    fields = asdict(record)
    # Preserve the ID of existing frame manifests that predate this optional field.
    if frame_size is None:
        del fields["frame_size"]
    return replace(record, id=_id("inspection", fields))


def sample(video: Video, interval: Interval, requested_times_us: list[int]) -> Inspection:
    """Sample one frame at or after each request, keeping explicit misses."""
    requests = tuple(requested_times_us)
    indices = _select(video, interval, requests)
    unique = tuple(sorted({index for index in indices if index is not None}))
    validate_source(video)
    version = _version("ffmpeg")
    pixels = _decode(video, unique)
    validate_source(video)
    frames = {index: _frame(video, index, hashlib.sha256(image).hexdigest())
              for index, image in zip(unique, pixels, strict=True)}
    return _inspection(
        video, interval, requests, indices, frames, version, (video.width, video.height),
    )


def validate_reference(video: Video, inspection: Inspection, frame_id: str) -> bytes:
    """Validate an inspection reference and replay its original RGB24 bytes."""
    validate_source(video)
    if inspection.video_id != video.id:
        raise VideoError("Inspection references a different video")
    indices = _select(video, inspection.requested_interval, inspection.requested_times_us)
    unique = tuple(sorted({index for index in indices if index is not None}))
    if len(unique) != len(inspection.frames):
        raise VideoError("Inspection does not contain the expected sampled frames")
    frames = {index: _frame(video, index, frame.rgb24_sha256)
              for index, frame in zip(unique, inspection.frames, strict=True)}
    frame_size = (video.width, video.height) if inspection.frame_size is not None else None
    if inspection != _inspection(
        video, inspection.requested_interval, inspection.requested_times_us,
        indices, frames, inspection.extraction_version, frame_size,
    ):
        raise VideoError("Inspection metadata or sampled frames do not match the reference")
    for index, frame in frames.items():
        if frame.id == frame_id:
            _reprobe(video)
            image, = _decode(video, (index,))
            validate_source(video)
            if hashlib.sha256(image).hexdigest() != frame.rgb24_sha256:
                raise VideoError("Replayed frame pixels differ from the recorded evidence")
            return image
    raise VideoError("Frame is not part of the inspection")


def _reprobe(video: Video) -> tuple[int | None, ...]:
    source = validate_source(video)
    probed, durations = _probe_source(source)
    if video != replace(probed, source_path=video.source_path, probe_version=video.probe_version):
        raise VideoError("Recorded video metadata differs from the source probe")
    return durations


def _clip_indices(video: Video, interval: Interval) -> range:
    interval.validate(video.duration_us)
    start = bisect_left(video.frame_pts, _source_pts(video, interval.start_us))
    stop = bisect_left(video.frame_pts, _source_pts(video, interval.end_us))
    if start == stop:
        raise VideoError("No displayed frame starts within the requested clip interval")
    return range(start, stop)


def _describe_clip(
    video: Video, requested: Interval, indices: range, tail_duration: int | None,
    artifact: Path, version: str,
) -> ClipInspection:
    if tail_duration is None or tail_duration <= 0:
        raise VideoError("The final selected source frame has no usable duration")
    clip, _ = _probe_source(artifact, require_clip=True)
    if len(clip.frame_pts) != len(indices) or clip.first_display_pts != 0:
        raise VideoError("Clip frame count or timestamp origin differs from the extraction")
    if (clip.width, clip.height) != (video.width, video.height):
        raise VideoError("Clip dimensions differ from the source")
    source_origin = video.frame_pts[indices.start]
    for index, clip_pts in zip(indices, clip.frame_pts, strict=True):
        source_elapsed = (video.frame_pts[index] - source_origin) * video.time_base
        if abs(clip_pts * clip.time_base - source_elapsed) > clip.time_base / 2:
            raise VideoError("Clip timestamps differ from the source beyond muxer rounding")
    source_end_pts = min(
        video.frame_pts[indices[-1]] + tail_duration,
        video.frame_pts[-1] + video.last_frame_duration_pts,
    )
    clip_end = (clip.frame_pts[-1] + clip.last_frame_duration_pts) * clip.time_base
    source_elapsed = (source_end_pts - source_origin) * video.time_base
    if abs(clip_end - source_elapsed) > clip.time_base:
        raise VideoError("Clip end differs from the source beyond muxer rounding")
    original_pixels = _decode(video, indices)
    clip_pixels = _decode(clip, range(len(indices)))
    if original_pixels != clip_pixels:
        raise VideoError("Clip pixels differ from the original footage")
    validate_source(video)
    validate_source(clip)
    frames = tuple(
        ClipFrame(_frame(video, index, hashlib.sha256(pixels).hexdigest()), clip_pts)
        for index, pixels, clip_pts in zip(indices, original_pixels, clip.frame_pts, strict=True)
    )
    actual = Interval(
        frames[0].source.source_time_us,
        ceil(video.time_at_pts(source_end_pts) * US_PER_SECOND),
    )
    record = ClipInspection(
        "", video.id, requested, actual, source_end_pts, clip.duration_us,
        clip.time_base_num, clip.time_base_den, clip.last_frame_duration_pts,
        frames, clip.sha256, version,
    )
    return replace(record, id=_id("clip", asdict(record)))


def extract_clip(video: Video, interval: Interval) -> tuple[ClipInspection, bytes]:
    """Extract a lossless video-only clip with checked source and clip clocks."""
    indices = _clip_indices(video, interval)
    durations = _reprobe(video)
    version = _version("ffmpeg")
    with tempfile.TemporaryDirectory() as directory:
        artifact = Path(directory) / "clip.mkv"
        result = _run(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-xerror",
            "-filter_threads", "1", "-copyts", "-noautorotate", "-i", video.source_path,
            "-map", f"0:{video.stream_index}", "-map_metadata", "-1", "-map_chapters", "-1",
            "-vf", (f"select='between(n,{indices.start},{indices.stop - 1})',"
                    "showinfo,setpts=PTS-STARTPTS"),
            "-frames:v", str(len(indices)), "-fps_mode", "passthrough",
            "-enc_time_base", "filter", "-threads", "1", "-c:v", "ffv1",
            "-flags:v", "+bitexact", "-fflags", "+bitexact", "-f", "matroska", str(artifact),
        )
        _verify_decoded_timestamps(video, indices, result.stderr)
        inspection = _describe_clip(video, interval, indices, durations[indices[-1]], artifact, version)
        return inspection, artifact.read_bytes()


def validate_clip(video: Video, inspection: ClipInspection, artifact: bytes) -> None:
    """Verify artifact bytes, timestamps and every frame against the source."""
    if (inspection.video_id != video.id
            or hashlib.sha256(artifact).hexdigest() != inspection.artifact_sha256):
        raise VideoError("Clip does not match its source or recorded artifact hash")
    indices = _clip_indices(video, inspection.requested_interval)
    durations = _reprobe(video)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "clip.mkv"
        path.write_bytes(artifact)
        replay = _describe_clip(
            video, inspection.requested_interval, indices, durations[indices[-1]], path,
            inspection.extraction_version,
        )
        if replay != inspection:
            raise VideoError("Clip inspection differs from replayed media")
