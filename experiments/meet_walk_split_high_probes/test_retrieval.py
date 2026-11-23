from dataclasses import replace

import pytest

from retrieval import QUESTIONS, load_analysis
from security_augmented.contracts import Interval


@pytest.fixture(scope="module")
def analysis():
    return load_analysis()


def test_archived_questions(analysis):
    approach, entry, clock, separation, missing = [analysis.ask(q) for q in QUESTIONS]
    for answer in (approach, entry, missing):
        assert answer.anchor is None and not answer.events
        assert "No grounded matching event" in answer.text
    assert [event.interval.start_us for event in clock.events] == [10_000_000]
    assert "Insufficient evidence" in separation.text and not separation.events
    assert analysis.ask("Did a person move?").events == analysis.timeline


def test_grounded_after(analysis):
    answer = analysis.ask("What happened after movement in the sunlit aisle?")
    assert answer.anchor == analysis.timeline[0]
    supported_and_unresolved = (*analysis.timeline, *analysis.unresolved)
    assert answer.events == tuple(sorted(
        (e for e in supported_and_unresolved if e.interval.start_us >= answer.anchor.interval.end_us),
        key=lambda e: (e.interval.start_us, e.interval.end_us),
    ))
    assert "Unresolved" in answer.text and "identity" in answer.text
    assert answer.anchor.citations[0].inspection_id in answer.text
    assert all(c.inspection_id in answer.text for e in answer.events for c in e.citations)
    assert answer.inspection is None


def test_before_during_and_boundaries(analysis):
    anchor = analysis.timeline[2]
    before = analysis.ask("What happened before the person walked toward the upper-left corridor area?")
    assert before.anchor == anchor and before.events
    assert all(e.interval.end_us <= anchor.interval.start_us for e in before.events)
    during = analysis.ask("What happened during the person walking toward the upper-left corridor area?")
    assert during.anchor == anchor
    assert during.events and all(e != anchor and anchor.interval.start_us <= e.interval.start_us
                                 and e.interval.end_us <= anchor.interval.end_us for e in during.events)


def test_ambiguous_missing_and_empty(analysis):
    duplicate = replace(analysis.timeline[0], interval=Interval(1, 9_520_001))
    ambiguous = replace(analysis, timeline=(*analysis.timeline, duplicate))
    query = "What happened after movement in the sunlit aisle?"
    assert "Several grounded events" in ambiguous.ask(query).text
    assert "No grounded matching event" in replace(analysis, observations=()).ask(query).text
    isolated = replace(analysis, timeline=analysis.timeline[:1], unresolved=())
    assert "No recorded findings" in isolated.ask(query, inspect_missing=True).text


def test_archived_approach_has_no_relational_verdict(analysis):
    import hashlib
    import json

    from jsonschema import Draft202012Validator

    from retrieval import RESULT
    from security_augmented.agents import _decision_schema
    from security_augmented.video import _decode
    from security_augmented.workflow import EVENT_LABELS

    event = next(e for e in analysis.timeline if e.interval.start_us == 3_520_000)
    identifier, = event.observation_ids
    observation = next(f.observation for f in analysis.observations if f.observation.id == identifier)
    assert "joining the other walking individual" in observation.description
    assert event.category == "person_moved" and event.verdict == "supported"
    assert "joining" not in event.reason
    assert "person_approached" not in EVENT_LABELS
    record = json.loads(RESULT.read_text())
    decision = next(row["decision"] for row in record["decisions"]
                    if row["candidate_id"] == identifier and row["decision"]["action"] == "verdict")
    schema = Draft202012Validator(_decision_schema("verification", {
        "candidate_id": identifier, "evidence": {identifier: {"category": event.category}},
    }))
    assert schema.is_valid(decision)
    assert not schema.is_valid({**decision, "relationship": "approached_each_other"})
    assert not schema.is_valid({
        **decision, "transition": {**decision["transition"], "relationship": "approached_each_other"},
    })

    frames = event.citations[0].frames
    indices = tuple(f.display_index for f in frames)
    assert indices[0] == 88 and indices[-1] == 238
    for frame, pixels in zip(frames, _decode(analysis.video, indices), strict=True):
        assert analysis.video.frame_pts[frame.display_index] == frame.pts
        assert analysis.video.time_at_pts(frame.pts) * 1_000_000 == frame.source_time_us
        assert hashlib.sha256(pixels).hexdigest() == frame.rgb24_sha256


def test_relational_prose_cannot_create_anchor(analysis):
    event = next(e for e in analysis.timeline if e.interval.start_us == 3_520_000)
    prose = "The two people approached each other."
    observations = tuple(
        replace(f, observation=replace(f.observation, description=prose))
        if f.observation.id in event.observation_ids else f for f in analysis.observations
    )
    counterfactual = replace(analysis, observations=observations, timeline=(replace(event, reason=prose),))
    archived = analysis.ask(QUESTIONS[0])
    assert counterfactual.ask(QUESTIONS[0]) == archived
    assert not archived.anchor and not archived.events
    assert not analysis.ask("What happened after the two people shook hands?").anchor
    assert not analysis.ask(QUESTIONS[3]).events

    later = analysis.ask("What happened after movement in the sunlit aisle?")
    disputed, = (e for e in later.events if e.interval.start_us == 20_000_000)
    assert disputed.verdict == "supported"
    assert "Recorded supported finding" in later.text
    assert "Temporal ordering alone cannot establish identity or continuity" in later.text
    assert "purple" not in later.text and "left to right" not in later.text
