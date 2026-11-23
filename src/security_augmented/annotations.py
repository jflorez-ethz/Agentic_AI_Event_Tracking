"""Read CAVIAR annotations and resolve the checked LeftBag display order."""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET

from .contracts import SCHEMA_VERSION, Video, VideoError

_LEFTBAG_XML = "9599de02b41369065f1c718ec9c934bf1d58b65dc969b88e36c08ca54ab52bb7"
_LEFTBAG_VIDEO = "8f5d1dbf43d58da1bce57ca1b3f9491b8467773cfd66d2846f62f7d38d4a45e7"


@dataclass(frozen=True)
class Box:
    xc: int
    yc: int
    width: int
    height: int


@dataclass(frozen=True)
class Hypothesis:
    id: str
    evaluation: str
    previous: str | None
    # Each field preserves its XML tag, text and optional evaluation value.
    fields: tuple[tuple[str, str, str | None], ...]


@dataclass(frozen=True)
class AnnotationEntity:
    id: str
    box: Box
    orientation: int | None
    appearance: str | None
    members: tuple[str, ...]
    hypotheses: tuple[Hypothesis, ...]


@dataclass(frozen=True)
class AnnotationFrame:
    number: int
    objects: tuple[AnnotationEntity, ...]
    groups: tuple[AnnotationEntity, ...]


@dataclass(frozen=True)
class AnnotationDataset:
    name: str
    sha256: str
    frames: tuple[AnnotationFrame, ...]
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class AlignedAnnotation:
    annotation: AnnotationFrame
    display_index: int
    source_pts: int
    source_time: Fraction


def _parse_entity(node: ET.Element) -> AnnotationEntity:
    box = node.find("box")
    if box is None:
        raise VideoError("Annotation entity has no box")
    bounds = Box(*(int(box.attrib[key]) for key in ("xc", "yc", "w", "h")))
    if min(bounds.width, bounds.height) <= 0:
        raise VideoError("Annotation box dimensions must be positive")
    orientation = node.findtext("orientation")
    hypotheses = tuple(
        Hypothesis(
            hypothesis.attrib["id"], hypothesis.attrib["evaluation"], hypothesis.get("prev"),
            tuple((field.tag, (field.text or "").strip(), field.get("evaluation"))
                  for field in hypothesis),
        )
        for hypothesis in node.findall("hypothesislist/hypothesis")
    )
    return AnnotationEntity(
        node.attrib["id"], bounds, int(orientation) if orientation is not None else None,
        node.findtext("appearance"),
        tuple(member.strip() for member in node.findtext("members", "").split(",")
              if member.strip()),
        hypotheses,
    )


def parse_annotations(path: Path) -> AnnotationDataset:
    """Read a CAVIAR XML dataset with a contiguous zero-based frame index."""
    try:
        data = Path(path).read_bytes()
        root = ET.fromstring(data)
        if root.tag != "dataset":
            raise VideoError("Annotation root must be a dataset")
        nodes = root.findall("frame")
        indices = tuple(int(node.attrib["number"]) for node in nodes)
        if not indices or sorted(indices) != list(range(len(indices))):
            raise VideoError("Annotation indices must be contiguous, unique and zero-based")
        frames = (
            AnnotationFrame(
                index,
                tuple(map(_parse_entity, node.findall("objectlist/object"))),
                tuple(map(_parse_entity, node.findall("grouplist/group"))),
            )
            for index, node in zip(indices, nodes, strict=True)
        )
        return AnnotationDataset(
            root.attrib["name"], hashlib.sha256(data).hexdigest(),
            tuple(sorted(frames, key=lambda frame: frame.number)),
        )
    except VideoError:
        raise
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        raise VideoError(f"Invalid annotation dataset: {path}") from exc


def align_leftbag(dataset: AnnotationDataset, video: Video) -> tuple[AlignedAnnotation, ...]:
    """Apply the visually supported same-index mapping for this asset pair."""
    if (dataset.sha256 != _LEFTBAG_XML or video.sha256 != _LEFTBAG_VIDEO
            or dataset.schema_version != SCHEMA_VERSION or video.schema_version != SCHEMA_VERSION
            or video.stream_index != 0 or len(video.frame_pts) != 1440
            or tuple(frame.number for frame in dataset.frames) != tuple(range(1439))):
        raise VideoError("Annotation alignment is only established for the checked LeftBag assets")
    return tuple(
        AlignedAnnotation(frame, frame.number, pts, video.time_at_pts(pts))
        for frame, pts in zip(dataset.frames, video.frame_pts)
    )
