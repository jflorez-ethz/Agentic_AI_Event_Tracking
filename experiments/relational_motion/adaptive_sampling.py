"""Local source replay and experimental admission rules. No provider calls."""
import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from contract import Mark, View, assess
from security_augmented.contracts import FrameEvidence, Interval
from security_augmented.video import _decode, ingest, sample

WINDOWS = {"overlap": Interval(6_000_000, 8_000_000), "paths": Interval(10_000_000, 14_520_001)}
ARCHIVE = Path("experiments/meet_walk_split_high_probes/sampling-live.4GdQOj")


@dataclass(frozen=True)
class Request:
    start_us: int
    end_us: int
    uncertainty: str
    question: str
    step_ms: int = 250


def choose(request, *, candidate, duration_us, sufficient, remaining_inspections, remaining_requests, seen):
    if sufficient:
        return "sufficient"
    if request is None:
        return "unresolved"
    start, end = request.start_us, request.end_us
    if (request.step_ms != 250 or not 0 <= start < end <= duration_us
            or end - start > 5_000_000 or max(start, candidate[0]) >= min(end, candidate[1])
            or not request.uncertainty.strip() or not request.question.strip()):
        return "invalid_request"
    if (start, end, request.step_ms) in seen:
        return "already_inspected"
    if min(remaining_inspections, remaining_requests) < 1:
        return "budget_exhausted"
    return "inspect"


def collect(save_images=None):
    video = ingest(Path("data/raw/Meet_WalkSplit_pts.mp4"))
    windows = {}
    for window, interval in WINDOWS.items():
        arms = []
        baseline = set()
        for step in (500, 250):
            archived = json.loads((ARCHIVE / f"step-{step}/input.json").read_text())
            if archived["source_sha256"] != video.sha256:
                raise ValueError("Source differs from archived sampling run")
            times = list(range(interval.start_us, interval.end_us, step * 1000))
            inspection = sample(video, interval, times)
            indices = tuple(frame.display_index for frame in inspection.frames)
            pixels = _decode(video, indices)
            for frame, rgb in zip(inspection.frames, pixels, strict=True):
                if (frame.pts != video.frame_pts[frame.display_index]
                        or frame.source_time_us != video.time_at_pts(frame.pts) * 1_000_000
                        or sha256(rgb).hexdigest() != frame.rgb24_sha256):
                    raise ValueError("Source replay differs from sampled frame")
            archived_frames = {f["display_index"]: f for f in archived["inspection"]["frames"]}
            if any(asdict(frame) != archived_frames.get(frame.display_index) for frame in inspection.frames):
                raise ValueError("Sample differs from archived frame reference")
            if save_images and step == 250:
                save_images(window, inspection.frames, pixels, (video.width, video.height))
            arms.append(dict(step_ms=step, inspection=asdict(inspection), frames=[
                asdict(frame) for frame in inspection.frames
            ], new_indices=sorted(set(indices) - baseline) if baseline else []))
            baseline = set(indices)
        windows[window] = arms
    return dict(video_id=video.id, source_sha256=video.sha256, size=[video.width, video.height], windows=windows)


# Approximate image-plane head locations from local visual review (x, y, radius).
# A missing mark records an unassessable view. No identity links were assigned.
MARKS = {
    150: ((122, 141, 4), (169, 150, 4)),
    163: ((130, 138, 4), (157, 146, 4)),
    250: ((93, 112, 4), (82, 135, 4)),
    325: ((64, 94, 4), (55, 137, 4)),
}


def evaluate(evidence, arm_index):
    overlap, paths = (
        tuple(FrameEvidence(**f) for f in evidence["windows"][window][arm_index]["frames"])
        for window in WINDOWS
    )

    def view(frame):
        marks = MARKS.get(frame.display_index)
        return View(frame.id, tuple(Mark(*mark) for mark in marks) if marks else None)

    early = {f.display_index: view(f) for f in overlap}
    late = {f.display_index: view(f) for f in paths}
    size = tuple(evidence["size"])
    convergence = (early[150], early[163])
    divergence = (late[250], late[325])
    return {
        "approach": assess("approach", overlap, convergence, size),
        "nearby": assess("nearby", overlap, convergence, size, nearby_frame_id=early[163].frame_id),
        "visible_divergence": assess("visible_divergence", paths, divergence, size, distinct_paths=True),
        "separation": assess("separation", overlap + paths, tuple(v for i, v in (*early.items(), *late.items()) if 163 <= i <= 325), size,
                             nearby_frame_id=early[163].frame_id, distinct_paths=True),
        "joining": assess("joining", overlap, convergence, size),
    }


if __name__ == "__main__":
    import sys

    evidence = collect()
    evidence["review_marks"] = MARKS
    evidence["review_results"] = {
        step: {claim: asdict(result) for claim, result in evaluate(evidence, index).items()}
        for index, step in enumerate((500, 250))
    }
    Path(sys.argv[1]).write_text(json.dumps(evidence, indent=2) + "\n")
