"""person_fell: a direct visual person finding checked by an ordered before/after source-frame pair."""
import pytest

from security_augmented.agents import AgentRun
from security_augmented.contracts import Interval, VideoError
from security_augmented.evidence import CorroborationRequired
from security_augmented.observation import FrameReference, Observation
from security_augmented.video import _run, ingest
from security_augmented.workflow import EVENT_LABELS, Budget, ReportingAgent
from test_visual_transitions import seed, source  # noqa: F401  (fixture)


def make_fall_video(path):
    """A tall 'upright' figure for 0-3 s, then a wide 'lying' figure on the floor for 3-8 s."""
    _run(
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=96x64:r=5:d=8",
        "-vf", "drawbox=x=40:y=10:w=10:h=44:color=white:t=fill:enable='lt(t,3)',"
               "drawbox=x=25:y=48:w=44:h=10:color=white:t=fill:enable='gte(t,3)'",
        "-c:v", "ffv1", str(path),
    )


@pytest.mark.parametrize(("times", "indices", "status"), [
    ((1_000_000, 2_000_000), (0, 1), "supported"),
    ((2_000_000,), (0, 0), "insufficient"),          # one frame cannot show both states
    ((1_000_000, 2_000_000), (1, 0), "insufficient"),  # after precedes before
    ((1_000_000, 2_000_000), (0, None), "rejected"),   # uncited after frame
])
def test_fall_transition_contract_uses_exact_source_pair(source, times, indices, status):
    initial = seed(source, "person_fell", times)
    run = AgentRun(source, None, None, Budget(max_inspections=0), [])
    frames = initial.citation.frames
    before = frames[indices[0]]
    after = frames[indices[1]] if indices[1] is not None else None
    action = {
        "verdict": "supported", "ids": ["seed"], "reason": "Upright before, lying on the floor after.",
        "transition": {"observation_id": "seed", "before_frame_id": before.id,
                       "after_frame_id": after.id if after else "uncited"},
    }
    visible = {"seed": initial}
    if status == "rejected":
        with pytest.raises(VideoError):
            run.verdict(initial, action, visible)
        return
    if status == "insufficient":
        with pytest.raises(CorroborationRequired):
            run.verdict(initial, action, visible)
        return
    event = run.finish_verification(initial, visible, *run.verdict(initial, action, visible), completed=True)
    assert (event.verdict, event.category) == ("supported", "person_fell")
    assert event.interval == Interval(before.source_time_us, after.source_time_us + 1)
    assert EVENT_LABELS["person_fell"] in ReportingAgent().render(source, (event,), [])


def test_person_entry_cannot_be_refined_into_a_fall(source):
    initial = seed(source, "person_enters_area", (1_000_000, 2_000_000))
    run = AgentRun(source, None, None, Budget(max_inspections=0), [])
    frames = initial.citation.frames
    action = {"verdict": "supported", "ids": ["seed"], "reason": "Only a posture change is visible.",
              "refinement": {"category": "person_fell", "observation_id": "seed",
                             "before_frame_id": frames[0].id, "after_frame_id": frames[1].id}}
    with pytest.raises(VideoError, match="refinement"):
        run.verdict(initial, action, {"seed": initial})


def test_fall_on_synthetic_video_reaches_timeline_report_and_questions(tmp_path):
    pytest.importorskip("langgraph")
    from security_augmented.observation import InferenceMetadata, ObservationResult
    from security_augmented.workflow import InspectionPlan, analyze_video

    path = tmp_path / "fall.mkv"
    make_fall_video(path)
    calls = []

    class Provider:
        def infer(self, request):
            assert "person_fell" in request.categories
            assert "person_fell only when cited frames show the same person upright" in request.prompt
            inspection = request.media.inspection
            if inspection.requested_interval.start_us != 0:
                return ObservationResult(InferenceMetadata("offline", "mock", None, "1", "1"), ())
            cited = inspection.frames[2:4]  # 2 s upright, 3 s lying
            observation = Observation(
                "fall", inspection.id, "person_fell",
                "A standing figure is upright, then lies horizontally on the floor.",
                FrameReference(tuple(f.id for f in cited)), "Fixed view.", "Cause unknown.",
            )
            return ObservationResult(InferenceMetadata("offline", "mock", None, "1", "1"), (observation,))

    def decide(role, context):
        calls.append(role)
        if role == "investigation":
            return {"action": "delegate", "ids": list(context["evidence"]), "dispositions": [], "reason": "Check it."}
        if role == "reporting":
            return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
        candidate = context["candidate_id"]
        framed = dict(zip(context["evidence"][candidate]["frame_times_us"],
                          context["evidence"][candidate]["frame_ids"], strict=True))
        return {
            "action": "verdict", "ids": [candidate], "verdict": "supported", "correspondence": [],
            "transition": {"observation_id": candidate, "before_frame_id": framed[2_000_000],
                           "after_frame_id": framed[3_000_000]},
            "reason": "Upright in the before frame, lying on the floor in the after frame.",
        }

    result = analyze_video(
        path, Provider(), decide=decide, controller="langgraph",
        plan=InspectionPlan(window_us=4_000_000, frame_step_us=1_000_000),
        budget=Budget(max_initial_windows=2, max_inspections=0, max_agent_calls=6),
    )
    assert calls == ["investigation", "verification", "reporting"]
    assert not result.unresolved
    (event,) = result.timeline
    assert (event.category, event.verdict) == ("person_fell", "supported")
    assert event.interval == Interval(2_000_000, 3_000_001)
    assert EVENT_LABELS["person_fell"] in result.report
    assert "00:02.000000–00:03.000000" in result.report

    for question in ("Did anyone fall?", "When did the person fall?", "Is someone lying on the floor?"):
        assert result.ask(question).events == result.timeline, question
    for question in ("Did a person enter the scene?", "Did someone place an object?", "What appeared in the video?"):
        assert not result.ask(question).events, question
