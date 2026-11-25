"""Provider-neutral inputs, results and evidence checks for visual inference."""
from __future__ import annotations


from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import hashlib
from typing import Protocol

from .relations import PERCEPTION_CLAIMS, Review, validate_review
from .contracts import (
    SCHEMA_VERSION, US_PER_SECOND, ClipInspection, FrameEvidence, Inspection,
    Interval, VideoError,
)


@dataclass(frozen=True)
class FrameSequenceInput:
    inspection: Inspection
    width: int
    height: int
    # RGB24 payloads follow the timestamped inspection frames in display order.
    rgb24_frames: tuple[bytes, ...]


@dataclass(frozen=True)
class ClipInput:
    inspection: ClipInspection
    artifact: bytes


@dataclass(frozen=True)
class ObservationRequest:
    media: FrameSequenceInput | ClipInput
    categories: tuple[str, ...]
    prompt: str
    schema_version: int = SCHEMA_VERSION
    relational: bool = False
    # Ask, for each insufficient_evidence observation, which event was suspected but not confirmed.
    possible_category: bool = False


@dataclass(frozen=True)
class FrameReference:
    frame_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClipReference:
    # Half-open, measured on the clip's clock rather than the source clock.
    interval: Interval


@dataclass(frozen=True)
class Observation:
    id: str
    inspection_id: str
    category: str
    description: str
    evidence: FrameReference | ClipReference
    visibility_limits: str
    uncertainty: str
    source_video_id: str | None = None
    inference_metadata: InferenceMetadata | None = None
    schema_version: int = SCHEMA_VERSION
    # Event suspected by Perception for an insufficient_evidence observation; None otherwise or when not asked.
    possible_category: str | None = None


Scalar = str | int | float | bool | None


@dataclass(frozen=True)
class InferenceMetadata:
    provider: str
    model_id: str
    model_version: str | None
    adapter_version: str
    prompt_version: str
    settings: tuple[tuple[str, Scalar], ...] = ()
    elapsed_ms: int | None = None
    usage: tuple[tuple[str, int | float], ...] = ()


@dataclass(frozen=True)
class ObservationResult:
    metadata: InferenceMetadata
    observations: tuple[Observation, ...]
    raw_response: str | None = None
    schema_version: int = SCHEMA_VERSION
    response_details: dict | None = None
    relation: Review | None = None
    relation_error: str | None = None


class ObservationProvider(Protocol):
    """An adapter maps verified media to provider inputs and parses the response."""

    def infer(self, request: ObservationRequest) -> ObservationResult: ...


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_request(request: ObservationRequest) -> None:
    """Check that the submitted payload bytes match the supplied inspection."""
    if (request.schema_version != SCHEMA_VERSION or not _has_text(request.prompt)
            or not request.categories or any(not _has_text(c) for c in request.categories)
            or len(set(request.categories)) != len(request.categories)):
        raise VideoError("Observation request has invalid schema, prompt or categories")
    media = request.media
    if request.relational and not isinstance(media, FrameSequenceInput):
        raise VideoError("Relational perception requires discrete source frames")
    if not isinstance(media, (ClipInput, FrameSequenceInput)):
        raise VideoError("Unsupported observation input")
    inspection = media.inspection
    expected = ClipInspection if isinstance(media, ClipInput) else Inspection
    if (not isinstance(inspection, expected)
            or inspection.schema_version != SCHEMA_VERSION or not inspection.frames):
        raise VideoError("Observation input requires a versioned, nonempty inspection")
    if isinstance(media, ClipInput):
        if (inspection.modality != "clip"
                or not isinstance(media.artifact, bytes)
                or hashlib.sha256(media.artifact).hexdigest() != inspection.artifact_sha256):
            raise VideoError("Clip input differs from the recorded inspection")
        return
    if (inspection.modality != "frames" or type(media.width) is not int
            or type(media.height) is not int or min(media.width, media.height) <= 0
            or inspection.frame_size != (media.width, media.height)
            or len(media.rgb24_frames) != len(inspection.frames)):
        raise VideoError("Frame input differs from the recorded inspection")
    frame_size = media.width * media.height * 3
    for frame, pixels in zip(inspection.frames, media.rgb24_frames, strict=True):
        if (not isinstance(pixels, bytes) or len(pixels) != frame_size
                or hashlib.sha256(pixels).hexdigest() != frame.rgb24_sha256):
            raise VideoError("Frame payload differs from the recorded inspection")


def resolve_clip_reference(
    inspection: ClipInspection, reference: ClipReference,
) -> tuple[FrameEvidence, ...]:
    """Return mapped source frames whose clip presentation overlaps the reference."""
    interval = reference.interval
    interval.validate(inspection.clip_duration_us)
    pts = tuple(frame.clip_pts for frame in inspection.frames)
    if not pts:
        raise VideoError("Clip reference requires decoded frames")
    ticks_per_us = 1 / (inspection.clip_time_base * US_PER_SECOND)
    start = interval.start_us * ticks_per_us
    end = interval.end_us * ticks_per_us
    if (start < pts[0] or end > pts[-1] + inspection.clip_last_frame_duration_pts):
        raise VideoError("Clip reference exceeds exact presentation bounds")
    # Include the frame already displayed at start, with all equal-PTS members.
    active_pts = pts[bisect_right(pts, start) - 1]
    first = bisect_left(pts, active_pts)
    stop = bisect_left(pts, end)
    return tuple(frame.source for frame in inspection.frames[first:stop])


def validate_result(request: ObservationRequest, result: ObservationResult) -> None:
    """Reject observations that cannot cite the submitted media."""
    validate_request(request)
    if result.relation is not None:
        if (not request.relational or result.relation.claim not in PERCEPTION_CLAIMS
                or result.relation.links):
            raise VideoError("Unexpected autonomous relation or identity links")
        frames = {frame.id: frame for frame in request.media.inspection.frames}
        validate_review(result.relation, frames, frames, (request.media.width, request.media.height))
    metadata = result.metadata
    if (result.schema_version != SCHEMA_VERSION or not all(map(_has_text, (
        metadata.provider, metadata.model_id, metadata.adapter_version, metadata.prompt_version,
    )))):
        raise VideoError("Inference result has invalid schema or metadata")
    media = request.media
    inspection = media.inspection
    submitted = {frame.id for frame in inspection.frames} if isinstance(media, FrameSequenceInput) else set()
    seen = set()
    for observation in result.observations:
        if (observation.schema_version != SCHEMA_VERSION
                or observation.inspection_id != inspection.id
                or (observation.source_video_id is not None
                    and observation.source_video_id != inspection.video_id)
                or (observation.inference_metadata is not None
                    and observation.inference_metadata != metadata)
                or observation.category not in request.categories
                or not all(map(_has_text, (
                    observation.id, observation.description, observation.visibility_limits,
                    observation.uncertainty,
                ))) or observation.id in seen):
            raise VideoError("Invalid observation fields or inspection reference")
        seen.add(observation.id)
        evidence = observation.evidence
        if isinstance(media, ClipInput) and isinstance(evidence, ClipReference):
            resolve_clip_reference(media.inspection, evidence)
        elif isinstance(media, FrameSequenceInput) and isinstance(evidence, FrameReference):
            if not evidence.frame_ids or any(frame_id not in submitted for frame_id in evidence.frame_ids):
                raise VideoError("Observation references frames outside the submitted inspection")
        else:
            raise VideoError("Observation evidence modality differs from the submitted input")


# ---------- neutral posture probe (person_on_floor facts; see floor_check.py) ----------

@dataclass(frozen=True)
class PostureRequest:
    """Ask, for each submitted frame, the posture, a stable identifier and the position of every visible person.

    The prompt never carries an observation's description or an event word: it is a neutral question.
    """
    media: FrameSequenceInput
    vocabulary: tuple[str, ...]
    prompt: str
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class PostureResult:
    metadata: InferenceMetadata
    # One entry per submitted frame, in order: {"frame_id": str, "persons": ({"id", "posture", "x", "y",
    # optionally "w", "h", "seat_nearby"}, ...)}.
    frames: tuple[dict, ...]
    raw_response: str | None = None
    schema_version: int = SCHEMA_VERSION


def validate_postures(request: PostureRequest, result: PostureResult) -> None:
    """Reject a posture answer that does not describe exactly the submitted frames with the imposed vocabulary."""
    if not isinstance(request.media, FrameSequenceInput) or not request.vocabulary or not _has_text(request.prompt):
        raise VideoError("Posture request needs discrete frames, a vocabulary and a prompt")
    validate_request(ObservationRequest(request.media, request.vocabulary, request.prompt))
    metadata = result.metadata
    if result.schema_version != SCHEMA_VERSION or not all(map(_has_text, (
            metadata.provider, metadata.model_id, metadata.adapter_version, metadata.prompt_version))):
        raise VideoError("Posture result has invalid schema or metadata")
    submitted = [frame.id for frame in request.media.inspection.frames]
    if [entry.get("frame_id") for entry in result.frames] != submitted:
        raise VideoError("Posture answer must describe each submitted frame once, in order")
    for entry in result.frames:
        persons = entry.get("persons")
        if not isinstance(persons, (list, tuple)):
            raise VideoError("Posture answer persons must be a list")
        ids = [p.get("id") if isinstance(p, dict) else None for p in persons]
        if any(not _has_text(i) for i in ids) or len(set(ids)) != len(ids):
            raise VideoError("Posture answer needs distinct person identifiers per frame")
        for person in persons:
            if person.get("posture") not in request.vocabulary:
                raise VideoError("Posture outside the imposed vocabulary")
            if not all(type(person.get(k)) in (int, float) and 0 <= person[k] <= 1 for k in ("x", "y")):
                raise VideoError("Person position must be within [0, 1]")
            if not all(type(person[k]) in (int, float) and 0 <= person[k] <= 1 for k in ("w", "h") if k in person):
                raise VideoError("Person box size must be within [0, 1]")
            if "seat_nearby" in person and type(person["seat_nearby"]) is not bool:
                raise VideoError("seat_nearby must be true or false")
