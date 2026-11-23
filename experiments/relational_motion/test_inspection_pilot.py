from pathlib import Path

import pytest

from inspection_pilot import InspectionPilot
from security_augmented.contracts import Interval
from security_augmented.graph_workflow import run_graph
from security_augmented.observation import FrameReference, InferenceMetadata, Observation, ObservationResult
from security_augmented.video import ingest, sample
from security_augmented.workflow import Budget, Citation, Finding


@pytest.fixture(scope="module")
def source():
    video = ingest(Path("data/raw/Meet_WalkSplit_pts.mp4"))
    interval = Interval(6_000_000, 8_000_000)
    baseline = sample(video, interval, list(range(interval.start_us, interval.end_us, 500_000)))
    observation = Observation("seed", baseline.id, "person_moved", "Visible movement.",
                              FrameReference(tuple(f.id for f in baseline.frames)), "Overlap", "Local only")
    return video, baseline, Finding(observation, Citation(video.id, baseline.id, "frames", interval, baseline.frames))


def inspect(step=250, start=6_000_000, end=8_000_000):
    return dict(action="inspect", modality="frames", start_us=start, end_us=end,
                sampling_step_ms=step, reason="Overlap timing is uncertain.",
                question="When are both silhouettes distinguishable?")


def run(source, actions, *, media_limit=2, budget=Budget(), initial=True):
    video, baseline, finding = source
    requests = []
    contexts = []
    actions = iter(actions)

    def decide(role, context):
        if role == "investigation":
            return dict(action="delegate", ids=["seed"], dispositions=[], reason="Inspect movement.")
        if role == "reporting":
            return dict(action="report", lead_id=None, emphasis="uncertainty", reason="Report unresolved.")
        contexts.append(context)
        return next(actions, dict(action="verdict", verdict="insufficient", ids=["seed"],
                                  correspondence=[], reason="Identity remains unresolved."))

    def review(request):
        requests.append(request)
        inspection = request.media.inspection
        witness = Observation("review", inspection.id, "person_moved", "Local silhouette motion",
                              FrameReference((inspection.frames[1].id,)), "Overlap", "Identity unknown")
        return ObservationResult(InferenceMetadata("offline", "fixture", None, "1", "1"), (witness,))

    pilot = InspectionPilot(video, decide, review, budget, [], media_limit=media_limit,
                            initial_inspections=(baseline,) if initial else ())
    events, _ = run_graph(pilot, (finding,))
    assert events[0].verdict == "insufficient"
    return pilot, requests, contexts


def test_fine_inspection_returns_source_evidence_to_verification(source):
    pilot, requests, contexts = run(source, [inspect(), inspect(start=6_100_000)])
    assert pilot.inspections == pilot.media_used == len(requests) == 1
    frames = requests[0].media.inspection.frames
    assert tuple(frames[::2]) == source[1].frames
    assert [f.display_index for f in frames[1::2]] == [157, 169, 182, 194]
    assert "review" in contexts[1]["evidence"]
    assert contexts[1]["last_tool_result"]["sampling_step_ms"] == 250
    assert contexts[2]["validation_feedback"]["code"] == "fine_limit"


@pytest.mark.parametrize(("action", "options", "code"), [
    (inspect(500), {}, "no_new_frames"),
    (inspect(start=5_000_000, end=10_000_001), {}, "fine_span"),
    (inspect(125), {}, "invalid_sampling"),
    (inspect() | {"question": " "}, {}, "missing_question"),
    (inspect(), {"media_limit": 0}, "media_budget"),
    (inspect(), {"budget": Budget(max_inspections=0)}, "inspection_budget_exhausted"),
    (inspect(), {"budget": Budget(max_verification_iterations=1)}, "execution_budget"),
    (inspect(), {"budget": Budget(max_agent_calls=3)}, "execution_budget"),
])
def test_rejections_spend_no_inspections_or_media(source, action, options, code):
    pilot, requests, _ = run(source, [action], **options)
    assert pilot.inspections == pilot.media_used == len(requests) == 0
    assert any((entry.details or {}).get("code") == code for entry in pilot.trace)


def test_verifier_can_skip_inspection(source):
    pilot, requests, _ = run(source, [])
    assert pilot.inspections == pilot.media_used == len(requests) == 0


def test_default_sampling_can_request_unseen_frames(source):
    pilot, requests, _ = run(source, [inspect(500, start=5_500_000)])
    assert pilot.media_used == 1
    assert requests[0].media.inspection.requested_times_us[1] == 6_000_000


def test_inline_payload_guard_runs_before_media_dispatch(source, monkeypatch):
    monkeypatch.setattr("security_augmented.gemini.MAX_INLINE_BYTES", 1)
    pilot, requests, _ = run(source, [inspect()])
    assert pilot.inspections == 1
    assert pilot.media_used == len(requests) == 0


def test_shifted_window_with_equivalent_frames_is_rejected(source):
    pilot, requests, _ = run(source, [inspect(500, start=5_999_999)])
    assert pilot.media_used == len(requests) == 0
    assert any((entry.details or {}).get("code") == "no_new_frames" for entry in pilot.trace)


def test_inspection_at_maximum_span_uses_at_most_twenty_frames(source):
    pilot, requests, _ = run(source, [inspect(end=11_000_000)])
    assert pilot.media_used == 1
    assert len(requests[0].media.inspection.frames) == 20


def test_successful_request_consumes_the_last_media_slot(source):
    pilot, requests, _ = run(source, [inspect(), inspect(500, start=5_500_000)], media_limit=1)
    assert pilot.media_used == pilot.inspections == len(requests) == 1
    assert any((entry.details or {}).get("code") == "media_budget" for entry in pilot.trace)
