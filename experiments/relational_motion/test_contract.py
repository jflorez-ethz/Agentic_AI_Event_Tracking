from pathlib import Path
import hashlib
import json

import pytest

from contract import Link, Mark, View, assess
from security_augmented.contracts import FrameEvidence
from security_augmented.video import _decode, ingest


def frame(index):
    return FrameEvidence(f"fixture-{index}", index, index, index * 40_000, f"hash-{index}")


def view(index, left, right, radius=1):
    return View(f"fixture-{index}", (Mark(left, 50, radius), Mark(right, 50, radius)))


FRAMES = tuple(frame(i) for i in range(3))


def test_approach_only_claims_decreasing_apparent_spacing():
    views = (view(0, 20, 80), view(1, 36, 64), view(2, 42, 58))
    result = assess("approach", FRAMES, views, (100, 100))
    assert result.status == "supported" and result.continuity == "unresolved"
    assert result.frame_ids == tuple(f.id for f in FRAMES)


def test_later_visible_divergence_does_not_link_to_an_earlier_pair():
    views = (view(0, 42, 58), view(1, 36, 64), view(2, 20, 80))
    result = assess("visible_divergence", FRAMES, views, (100, 100), distinct_paths=True)
    assert result.status == "supported" and result.continuity == "unresolved"
    assert assess("separation", FRAMES, views, (100, 100), distinct_paths=True).status == "insufficient"


def test_separation_requires_nearby_reference_and_both_reviewed_links():
    views = (view(0, 42, 58), view(1, 36, 64), view(2, 20, 80))
    links = (Link(FRAMES[0].id, FRAMES[1].id, (0, 1)), Link(FRAMES[1].id, FRAMES[2].id, (0, 1)))
    result = assess("separation", FRAMES, views, (100, 100), distinct_paths=True,
                    nearby_frame_id=FRAMES[0].id, links=links)
    assert result.status == "supported" and result.continuity == "reviewed"
    assert assess("separation", FRAMES, views, (100, 100), distinct_paths=True,
                  nearby_frame_id=FRAMES[0].id, links=links[:1]).status == "insufficient"


def test_ambiguous_crossing_is_not_bridged():
    views = (view(0, 42, 58), View(FRAMES[1].id, None), view(2, 20, 80))
    assert assess("separation", FRAMES, views, (100, 100), distinct_paths=True,
                  nearby_frame_id=FRAMES[0].id, links=()).status == "insufficient"
    uncertain = (view(0, 42, 58, radius=7), view(2, 40, 60, radius=7))
    assert assess("visible_divergence", FRAMES, uncertain, (100, 100), distinct_paths=True).status == "insufficient"


def test_joining_is_not_inferred_even_with_a_supported_approach():
    views = (view(0, 20, 80), view(2, 42, 58))
    assert assess("joining", FRAMES, views, (100, 100)).status == "insufficient"


def test_nearby_and_separate_paths_remain_local_descriptions():
    first = view(0, 42, 58)
    views = (first, view(2, 20, 80))
    nearby = assess("nearby", FRAMES, views, (100, 100), nearby_frame_id=first.frame_id)
    assert nearby.status == "supported" and nearby.frame_ids == (first.frame_id,)
    assert nearby.interval_us == (0, 1)
    assert assess("distinct_paths", FRAMES, views, (100, 100), distinct_paths=True).continuity == "unresolved"


def test_different_radii_do_not_distinguish_coincident_targets():
    duplicate_position = View(FRAMES[0].id, (Mark(50, 40, 1), Mark(50, 40, 2)))
    nearby = assess("nearby", FRAMES, (duplicate_position,), (100, 100),
                    nearby_frame_id=duplicate_position.frame_id)
    assert nearby.status == "insufficient"
    divergence = assess("visible_divergence", FRAMES, (duplicate_position, view(1, 20, 80)),
                        (100, 100), distinct_paths=True)
    assert divergence.status == "insufficient"
    overlap = View(FRAMES[1].id, duplicate_position.marks)
    links = (Link(FRAMES[0].id, FRAMES[1].id, (0, 1)), Link(FRAMES[1].id, FRAMES[2].id, (0, 1)))
    separation = assess("separation", FRAMES, (view(0, 42, 58), overlap, view(2, 20, 80)),
                        (100, 100), distinct_paths=True,
                        nearby_frame_id=FRAMES[0].id, links=links)
    assert separation.status == "insufficient" and separation.continuity == "unresolved"


@pytest.mark.parametrize("views", [
    (view(0, 20, 80), view(9, 42, 58)),
    (view(2, 42, 58), view(0, 20, 80)),
    (view(0, 20, 80), view(0, 42, 58)),
    (view(0, 20, 110), view(2, 42, 58)),
])
def test_invalid_frame_or_pixel_references_are_rejected(views):
    with pytest.raises(ValueError):
        assess("approach", FRAMES, views, (100, 100))


def test_archived_frames_resolve_without_inventing_a_relational_verdict():
    result = json.loads(Path(
        "experiments/meet_walk_split_high_probes/verification.Uk6X57/run/result.json"
    ).read_text())
    video = ingest(Path("data/raw/Meet_WalkSplit_pts.mp4"))
    assert video.sha256 == result["source_sha256"]
    selected = {150, 163, 175, 188, 250, 300, 325, 350}
    records = {f["display_index"]: f for e in result["events"] if e["verdict"] == "supported"
               for c in e["citations"] for f in c["frames"] if f["display_index"] in selected}
    assert records.keys() == selected
    indices = sorted(selected)
    for index, rgb in zip(indices, _decode(video, tuple(indices)), strict=True):
        frame = records[index]
        assert video.frame_pts[index] == frame["pts"]
        assert video.time_at_pts(frame["pts"]) * 1_000_000 == frame["source_time_us"]
        assert hashlib.sha256(rgb).hexdigest() == frame["rgb24_sha256"]
    for event in result["events"]:
        if event["verdict"] == "supported":
            assert event["category"] == "person_moved"
    # Archived citations resolve. The archived verdict has no reviewed endpoint marks or pair links.
    frames = tuple(FrameEvidence(**records[i]) for i in indices)
    for claim in ("approach", "visible_divergence", "separation"):
        assert assess(claim, frames, (), (video.width, video.height)).status == "insufficient"


def test_separation_cannot_skip_a_cited_intermediate_view():
    views = (view(0, 42, 58), view(2, 20, 80))
    shortcut = (Link(FRAMES[0].id, FRAMES[2].id, (0, 1)),)
    assert assess("separation", FRAMES, views, (100, 100), distinct_paths=True,
                  nearby_frame_id=FRAMES[0].id, links=shortcut).status == "insufficient"
