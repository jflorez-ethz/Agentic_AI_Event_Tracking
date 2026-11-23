"""Versioned records for source video and inspected frame evidence."""

from dataclasses import dataclass
from fractions import Fraction

SCHEMA_VERSION = 1
US_PER_SECOND = 1_000_000


class VideoError(ValueError):
    """A source, extraction, or evidence reference could not be verified."""


@dataclass(frozen=True)
class Interval:
    start_us: int
    end_us: int

    def validate(self, duration_us: int) -> None:
        if (type(self.start_us) is not int or type(self.end_us) is not int
                or not 0 <= self.start_us < self.end_us <= duration_us):
            raise VideoError("Interval must be nonempty and within the source")


@dataclass(frozen=True)
class Video:
    id: str
    sha256: str
    source_path: str
    stream_index: int
    duration_us: int
    time_base_num: int
    time_base_den: int
    first_display_pts: int
    frame_pts: tuple[int, ...]
    last_frame_duration_pts: int
    width: int
    height: int
    probe_version: str
    schema_version: int = SCHEMA_VERSION

    @property
    def time_base(self) -> Fraction:
        return Fraction(self.time_base_num, self.time_base_den)

    def time_at_pts(self, pts: int) -> Fraction:
        """Return exact source-relative time in seconds."""
        return (pts - self.first_display_pts) * self.time_base


@dataclass(frozen=True)
class FrameEvidence:
    id: str
    display_index: int
    pts: int
    source_time_us: int
    rgb24_sha256: str
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class Inspection:
    id: str
    video_id: str
    requested_interval: Interval
    requested_times_us: tuple[int, ...]
    modality: str
    selection_policy: str
    pixel_format: str
    extraction_version: str
    frames: tuple[FrameEvidence, ...]
    frame_ids_by_request: tuple[str | None, ...]
    status: str
    schema_version: int = SCHEMA_VERSION
    frame_size: tuple[int, int] | None = None


@dataclass(frozen=True)
class ClipFrame:
    source: FrameEvidence
    clip_pts: int


@dataclass(frozen=True)
class ClipInspection:
    id: str
    video_id: str
    requested_interval: Interval
    actual_source_interval: Interval
    source_end_pts: int
    clip_duration_us: int
    clip_time_base_num: int
    clip_time_base_den: int
    clip_last_frame_duration_pts: int
    frames: tuple[ClipFrame, ...]
    artifact_sha256: str
    extraction_version: str
    modality: str = "clip"
    container: str = "matroska"
    codec: str = "ffv1"
    status: str = "complete"
    schema_version: int = SCHEMA_VERSION

    @property
    def clip_time_base(self) -> Fraction:
        return Fraction(self.clip_time_base_num, self.clip_time_base_den)
