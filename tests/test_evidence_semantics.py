from dataclasses import replace
from types import SimpleNamespace

import pytest

from security_augmented.agents import AgentRun, CorroborationRequired
from security_augmented.contracts import FrameEvidence, Interval, VideoError
from security_augmented.observation import FrameReference, Observation
from security_augmented.workflow import ArchivedInspection, Budget, Citation, Finding


def finding(identifier, category, description, frame_times):
    frames = tuple(FrameEvidence(f"frame-{t}", t, t, t, "hash") for t in frame_times)
    span = Interval(frame_times[0], frame_times[-1] + 1)
    citation = Citation("video", identifier, "frames", span, frames)
    obs = Observation(identifier, identifier, category, description, FrameReference(tuple(f.id for f in frames)),
                      "Partial view.", "Unknown.")
    return Finding(obs, citation)


def runner(entries=()):
    return AgentRun(SimpleNamespace(duration_us=100), None, lambda *_: entries, Budget(), [])


def test_correspondence_needs_grounded_explicit_assessment():
    a = finding("a", "object_placed", "A person sets down a red bag.", (10, 20))
    b = finding("b", "object_placed", "A red bag is set down.", (10, 19))
    run = runner()
    visible = {"a": a, "b": b}
    action = {"verdict": "supported", "ids": ["a", "b"], "reason": "test"}
    with pytest.raises(CorroborationRequired):
        run.verdict(a, action, visible)
    assessment = dict(id="b", status="same_event", seed_quote="red bag",
                      other_quote="red bag", shared_frame_id="frame-10")
    assert run.verdict(a, {**action, "correspondence": [assessment]}, visible)[1] == "supported"
    for classification in ("different_events", "unresolved"):
        with pytest.raises(CorroborationRequired):
            run.verdict(a, {**action, "correspondence": [dict(
                assessment, status=classification, shared_frame_id=None,
            )]}, visible)
    with pytest.raises(VideoError):
        run.verdict(a, {**action, "correspondence": [dict(assessment, other_quote="invented")]}, visible)


def test_unrelated_overlapping_removal_does_not_block_grounded_placement():
    a = finding("a", "object_placed", "A red bag is set down.", (10, 20))
    b = finding("b", "object_placed", "The red bag is set down.", (10, 19))
    c = finding("c", "object_removed", "A blue box is picked up.", (10, 18))
    assert runner().verdict(a, {
        "verdict": "supported", "ids": ["a", "b"], "reason": "test",
        "correspondence": [dict(id="b", status="same_event", seed_quote="red bag",
                                other_quote="red bag", shared_frame_id="frame-10"),
                           dict(id="c", status="different_events", seed_quote="red bag",
                                other_quote="blue box", shared_frame_id=None)],
    }, {"a": a, "b": b, "c": c})[1] == "supported"


@pytest.mark.parametrize(("coverage", "status"), [
    ((), "missing"), ((Interval(12, 16),), "partial"), ((Interval(10, 20),), "covered_without_findings"),
])
def test_archive_coverage_and_out_of_scope_evidence(coverage, status):
    a = finding("a", "object_placed", "Bag placed.", (9, 19))
    outside = finding("outside", "object_placed", "Bag placed.", (9, 18))
    entries = (ArchivedInspection("fixture", "frames", Interval(5, 25), "success", (outside,), coverage=coverage),)
    visible = {"a": a}
    result = runner(entries).reinspect(a, {"modality": "frames", "start_us": 10, "end_us": 20}, visible)
    assert result["status"] == status
    assert result["excluded_citation_spans"] == [{"id": "outside", "start_us": 9, "end_us": 19}]
    assert "outside" not in visible


def test_different_placements_are_not_corroborating_even_with_overlap():
    a = finding("a", "object_placed", "A red bag is placed beside a door.", (10, 21))
    b = finding("b", "object_placed", "A blue box is placed on a desk.", (10, 19))
    with pytest.raises(CorroborationRequired):
        runner().verdict(a, {
            "verdict": "supported", "ids": ["a", "b"], "reason": "test",
            "correspondence": [dict(id="b", status="different_events", seed_quote="red bag",
                                    other_quote="blue box", shared_frame_id=None)],
        }, {"a": a, "b": b})


def test_partial_completion_renders_without_calling_a_blocked_reporter():
    from security_augmented.workflow import Decision

    run = runner()
    run.trace.extend([
        Decision("investigation", "delegate", "fixture", ("a", "b")),
        Decision("verification", "verdict", "supported", ("a",), details={"completed": True}),
        Decision("verification", "verdict", "unfinished", ("b",), details={"completed": False}),
    ])
    assert run.completion()["verification"] == "partial"
    assert run.completion()["completed_checks"] == 1


def test_provider_status_is_retained_without_recording_error_body():
    from unittest.mock import Mock

    from security_augmented.agents import AgentModels, GeminiDecider
    from security_augmented.gemini import GeminiAdapter

    class Failure(Exception):
        code = 503
        status = "UNAVAILABLE"
        response = SimpleNamespace(headers={"retry-after": "12", "authorization": "secret"})

    client = Mock()
    client.models.generate_content.side_effect = Failure("secret error body")
    decider = GeminiDecider(GeminiAdapter(client=client), AgentModels())
    with pytest.raises(VideoError):
        decider("verification", {})
    call, = decider.calls
    assert (call["http_status"], call["provider_status"], call["retry_after_seconds"]) == (503, "UNAVAILABLE", 12)
    assert "secret" not in repr(call)
    client.models.generate_content.assert_called_once()


def test_covered_findings_and_failed_archive_are_distinct():
    a = finding("a", "object_placed", "Bag placed.", (10, 19))
    requested = Interval(10, 20)
    action = {"modality": "frames", "start_us": 10, "end_us": 20}
    for entry, expected in [
        (ArchivedInspection("fixture", "frames", requested, "success", (a,), coverage=(requested,)),
         "covered_with_findings"),
        (ArchivedInspection("fixture", "frames", requested, "failed"), "failed"),
    ]:
        result = runner((entry,)).reinspect(a, action, {})
        assert result["status"] == expected
