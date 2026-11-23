"""Evidence contract for typed relationships between visible people."""

from dataclasses import dataclass
from itertools import pairwise
from math import dist, isfinite

from .contracts import FrameEvidence, Interval, VideoError


@dataclass(frozen=True)
class Mark:
    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class View:
    frame_id: str
    # Two distinct visible people, marked at comparable points (e.g. feet).
    # None records overlap, occlusion or an otherwise unassessable view.
    marks: tuple[Mark, Mark] | None


@dataclass(frozen=True)
class Link:
    before_id: str
    after_id: str
    # The position in the tuple is the earlier mark; its value is the later
    # mark. The reviewer must see both links and resolve any overlap.
    correspondence: tuple[int, int]


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    frame_ids: tuple[str, ...]
    interval_us: tuple[int, int] | None
    continuity: str = "unresolved"


def _spacing(marks):
    first, second = marks
    distance = dist((first.x, first.y), (second.x, second.y))
    uncertainty = first.radius + second.radius
    return max(0, distance - uncertainty), distance + uncertainty


def _distinct_positions(view):
    if view.marks is None:
        return False
    a, b = view.marks
    return (a.x, a.y) != (b.x, b.y)


def assess(
    claim: str, cited: tuple[FrameEvidence, ...], views: tuple[View, ...], size: tuple[int, int], *,
    distinct_paths: bool = False, nearby_frame_id: str | None = None, links: tuple[Link, ...] = (),
) -> Result:
    """Check whether supplied visual review meets a specific evidence contract."""
    frames = {f.id: f for f in cited}
    if len(frames) != len(cited) or any(a.source_time_us >= b.source_time_us for a, b in pairwise(cited)):
        raise ValueError("Source citations must be distinct and chronological")
    if any(v.frame_id not in frames for v in views):
        raise ValueError("Uncited view")
    times = [frames[v.frame_id].source_time_us for v in views]
    if any(a >= b for a, b in pairwise(times)):
        raise ValueError("Views must be distinct and chronological")
    width, height = size
    for view in views:
        if view.marks is None:
            continue
        if len(view.marks) != 2 or view.marks[0] == view.marks[1]:
            raise ValueError("Expected two distinguishable person marks")
        for mark in view.marks:
            if (not all(isfinite(n) for n in (mark.x, mark.y, mark.radius))
                    or not (0 <= mark.x < width and 0 <= mark.y < height and mark.radius >= 0)):
                raise ValueError("Mark outside source image or invalid uncertainty")
    view_ids = tuple(v.frame_id for v in views)
    if nearby_frame_id is not None and nearby_frame_id not in view_ids:
        raise ValueError("Nearby judgment must cite a supplied view")
    steps = set(pairwise(view_ids))
    link_pairs = {(link.before_id, link.after_id) for link in links}
    if len(link_pairs) != len(links) or any(
        (link.before_id, link.after_id) not in steps or link.correspondence not in ((0, 1), (1, 0))
        for link in links
    ):
        raise ValueError("Continuity links must reference adjacent views and both distinct targets")

    def finish(status, reason, continuity="unresolved"):
        return Result(status, reason, view_ids, (times[0], times[-1] + 1) if times else None, continuity)

    if claim not in {"approach", "distinct_paths", "nearby", "visible_divergence", "separation"}:
        return finish("insufficient", "Social joining, intent and interaction are outside this contract")
    if claim == "nearby":
        if any(v.frame_id == nearby_frame_id and _distinct_positions(v) for v in views):
            time = frames[nearby_frame_id].source_time_us
            return Result("supported", "Reviewer observed two nearby visible people",
                          (nearby_frame_id,), (time, time + 1))
        return finish("insufficient", "Missing a cited proximity assessment of two visible people")
    if len(views) < 2 or views[0].marks is None or views[-1].marks is None:
        return finish("insufficient", "Two distinguishable people are required at both endpoints")
    if frames[views[0].frame_id].rgb24_sha256 == frames[views[-1].frame_id].rgb24_sha256:
        return finish("insufficient", "Endpoint images are unchanged")
    before_low, before_high = _spacing(views[0].marks)
    after_low, after_high = _spacing(views[-1].marks)
    if claim == "approach":
        if after_high < before_low:
            return finish("supported", "Apparent image-plane spacing decreased beyond marking uncertainty")
        return finish("insufficient", "Decreasing apparent spacing is unclear")
    if not distinct_paths or not all(_distinct_positions(view) for view in (views[0], views[-1])):
        return finish("insufficient", "Missing a visual assessment of two distinguishable paths")
    if claim == "distinct_paths":
        return finish("supported", "Reviewer observed two distinguishable paths in this window")
    if after_low <= before_high:
        return finish("insufficient", "Increasing apparent spacing is unclear")
    if claim == "visible_divergence":
        return finish("supported", "Two distinguishable paths with increasing apparent spacing in this window")
    span_ids = tuple(f.id for f in cited if times[0] <= f.source_time_us <= times[-1])
    if (nearby_frame_id != views[0].frame_id or span_ids != view_ids
            or not all(_distinct_positions(view) for view in views) or link_pairs != steps):
        return finish("insufficient", "Same-pair separation needs a nearby start and both links through every cited view")
    return finish("supported", "Reviewer linked both nearby people through the later divergence", "reviewed")


RELATION_LABELS = {
    "approach": "Apparent convergence in the image",
    "nearby": "Two visible people near each other",
    "visible_divergence": "Local divergence in the image",
    "separation": "Same-pair separation under reviewed correspondence",
    "unresolved": "Person relationship unresolved",
}


@dataclass(frozen=True)
class Review:
    claim: str
    interval: Interval
    views: tuple[View, ...]
    distinct_paths: bool = False
    nearby_frame_id: str | None = None
    links: tuple[Link, ...] = ()


def validate_review(review, available, known, size):
    """Validate reviewed views against canonical evidence available to the workflow."""
    if (review.claim not in RELATION_LABELS or not review.views
            or type(review.distinct_paths) is not bool
            or any(type(n) is not int for n in (review.interval.start_us, review.interval.end_us))
            or any(type(index) is not int for link in review.links for index in link.correspondence)
            or any(type(number) not in (int, float) for view in review.views for mark in view.marks or ()
                   for number in (mark.x, mark.y, mark.radius))):
        raise VideoError("Unknown relational claim or missing reviewed views")
    if any(view.frame_id not in available for view in review.views):
        raise VideoError("Review references a frame outside visible source evidence")
    frames = tuple(sorted(known.values(), key=lambda frame: frame.source_time_us))
    try:
        result = assess(review.claim, frames, review.views, size, distinct_paths=review.distinct_paths,
                        nearby_frame_id=review.nearby_frame_id, links=review.links)
    except ValueError as exc:
        raise VideoError(str(exc)) from exc
    if result.interval_us != (review.interval.start_us, review.interval.end_us):
        raise VideoError("Relational interval must match the cited evidence bracket")
    if review.claim == "unresolved":
        return Result("insufficient", "Visibility or person correspondence remains unresolved",
                      result.frame_ids, result.interval_us)
    if review.claim == "separation" and result.status == "supported":
        # Sparse links cannot bridge a missing 2 FPS view. Allow timestamp quantization
        # up to 50 ms for this opt-in contract.
        times = [known[identifier].source_time_us for identifier in result.frame_ids]
        if any(right - left > 550_000 for left, right in pairwise(times)):
            return Result("insufficient", "Reviewed correspondence has a temporal evidence gap",
                          result.frame_ids, result.interval_us)
    return result


def review_from_dict(row):
    """Restore an explicit local review record, preserving input types for validation."""
    return Review(
        row["claim"], Interval(**row["interval"]),
        tuple(View(view["frame_id"], None if view["marks"] is None else tuple(
            Mark(**mark) for mark in view["marks"]
        )) for view in row["views"]),
        row.get("distinct_paths", False), row.get("nearby_frame_id"),
        tuple(Link(link["before_id"], link["after_id"], tuple(link["correspondence"]))
              for link in row.get("links", ())),
    )


# Single perception judgments are eligible for local relations. Identity links
# require evidence that this autonomous interface does not establish.
PERCEPTION_CLAIMS = ("approach", "nearby", "visible_divergence", "unresolved")


def perception_review(row, frames, size):
    """Resolve a media response's local frame labels and validate its bracket."""
    fields = {"claim", "interval", "views", "distinct_paths", "nearby_frame_label"}
    if not isinstance(row, dict) or row.keys() != fields or row["claim"] not in PERCEPTION_CLAIMS:
        raise VideoError("Invalid autonomous relation fields or unsupported identity claim")
    labels = {f"F{i}": frame.id for i, frame in enumerate(frames, 1)}
    available = {frame.id: frame for frame in frames}
    try:
        views = []
        for view in row["views"]:
            if view.keys() != {"frame_label", "marks"}:
                raise ValueError("Unexpected view fields")
            views.append({"frame_id": labels[view["frame_label"]], "marks": view["marks"]})
        near = row["nearby_frame_label"]
        review = review_from_dict({
            "claim": row["claim"], "interval": row["interval"], "views": views,
            "distinct_paths": row["distinct_paths"],
            "nearby_frame_id": labels[near] if near is not None else None,
        })
    except (AttributeError, TypeError, KeyError, ValueError) as exc:
        raise VideoError("Invalid relational marks, interval or submitted frame labels") from exc
    if review.claim == "nearby" and (len(review.views) != 1 or review.nearby_frame_id is None):
        raise VideoError("A nearby proposal must cite one reference view")
    validate_review(review, available, available, size)
    return review
