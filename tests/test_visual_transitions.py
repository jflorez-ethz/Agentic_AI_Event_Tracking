from dataclasses import replace

import pytest

from security_augmented.agents import AgentRun
from security_augmented.contracts import Interval, VideoError
from security_augmented.evidence import CorroborationRequired
from security_augmented.observation import FrameReference, Observation
from security_augmented.video import ingest, sample
from security_augmented.workflow import Budget, Citation, Finding, ReportingAgent
from test_new_video import make_video


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "block.mkv"
    make_video(path)
    return ingest(path)


def seed(video, category, times):
    inspection = sample(video, Interval(0, 8_000_000), list(times))
    frames = inspection.frames
    span = Interval(frames[0].source_time_us, frames[-1].source_time_us + 1)
    return Finding(Observation(
        "seed", inspection.id, category, "The rectangle changes visibility between the cited frames.",
        FrameReference(tuple(f.id for f in frames)), "Fixed camera view.", "Cause unknown.",
    ), Citation(video.id, inspection.id, "frames", span, frames))


@pytest.mark.parametrize(("category", "times"), [
    ("object_placed", (1_000_000, 2_000_000)),
    ("object_removed", (4_000_000, 5_000_000, 6_000_000, 7_000_000)),
])
def test_action_contract_requires_more_than_an_initial_transition(source, category, times):
    initial = seed(source, category, times)
    run = AgentRun(source, None, None, Budget(max_inspections=0), [])
    action = {"verdict": "supported", "ids": ["seed"], "reason": "The image changes."}
    with pytest.raises(CorroborationRequired):
        run.verdict(initial, action, {"seed": initial})
    repeated = Finding(replace(initial.observation, id="repeated", inspection_id="second"),
                       replace(initial.citation, inspection_id="second"))
    with pytest.raises(CorroborationRequired):
        run.verdict(initial, {**action, "ids": ["seed", "repeated"], "correspondence": [{
            "id": "repeated", "status": "same_event", "seed_quote": "changes visibility",
            "other_quote": "changes visibility", "shared_frame_id": initial.citation.frames[0].id,
        }]}, {"seed": initial, "repeated": repeated})


@pytest.mark.parametrize(("category", "times", "indices", "status"), [
    ("object_appeared", (1_000_000, 2_000_000), (0, 1), "supported"),
    ("object_disappeared", (4_000_000, 5_000_000, 6_000_000, 7_000_000), (1, 2), "supported"),
    ("object_placed", (1_000_000, 2_000_000), (0, 1), "rejected"),
    ("object_appeared", (0, 1_000_000), (0, 1), "insufficient"),
    ("object_appeared", (2_000_000,), (0, 0), "insufficient"),
    ("object_disappeared", (5_000_000, 6_000_000), (1, 0), "insufficient"),
    ("object_appeared", (1_000_000, 2_000_000), (0, None), "rejected"),
])
def test_model_assessed_visual_transition_uses_exact_source_pair(source, category, times, indices, status):
    initial = seed(source, category, times)
    run = AgentRun(source, None, None, Budget(max_inspections=0), [])
    frames = initial.citation.frames
    before = frames[indices[0]]
    after = frames[indices[1]] if indices[1] is not None else None
    action = {
        "verdict": "supported", "ids": ["seed"], "reason": "The cited states show a visibility change.",
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
    assert event.verdict == "supported"
    assert event.interval == Interval(before.source_time_us, after.source_time_us + 1)
    assert event.citations == (initial.citation,)
    rendered = ReportingAgent().render(source, (event,), [])
    assert "became visible" in rendered or "ceased to be visible" in rendered
    assert "was placed" not in rendered and "was removed" not in rendered


def test_visual_transitions_complete_graph_without_reinspection(source):
    pytest.importorskip("langgraph")
    from security_augmented.observation import InferenceMetadata, ObservationResult
    from security_augmented.workflow import InspectionPlan, analyze_video

    calls = []

    class Provider:
        def infer(self, request):
            inspection = request.media.inspection
            assert request.media.inspection.modality == "frames"
            assert {"object_appeared", "object_disappeared"} <= set(request.categories)
            first = inspection.requested_interval.start_us == 0
            category = "object_appeared" if first else "object_disappeared"
            cited = inspection.frames[1:3] if first else inspection.frames
            observation = Observation(
                category, inspection.id, category,
                "A rectangle becomes visible." if first else "A rectangle ceases to be visible.",
                FrameReference(tuple(f.id for f in cited)), "Fixed view.", "Cause unknown.",
            )
            return ObservationResult(InferenceMetadata("offline", "mock", None, "1", "1"), (observation,))

    def decide(role, context):
        calls.append(role)
        if role == "investigation":
            return {"action": "delegate", "ids": list(context["evidence"]), "dispositions": [], "reason": "Review both."}
        if role == "reporting":
            return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
        candidate = context["candidate_id"]
        framed = dict(zip(context["evidence"][candidate]["frame_times_us"],
                          context["evidence"][candidate]["frame_ids"], strict=True))
        before, after = (1_000_000, 2_000_000) if candidate == "object_appeared" else (5_000_000, 6_000_000)
        return {
            "action": "verdict", "ids": [candidate], "verdict": "supported", "correspondence": [],
            "transition": {"observation_id": candidate, "before_frame_id": framed[before], "after_frame_id": framed[after]},
            "reason": "The cited frames show different visibility states.",
        }

    result = analyze_video(
        source.source_path, Provider(), decide=decide, controller="langgraph",
        plan=InspectionPlan(window_us=4_000_000, frame_step_us=1_000_000),
        budget=Budget(max_initial_windows=2, max_inspections=0, max_agent_calls=6),
    )
    assert calls == ["investigation", "verification", "verification", "reporting"]
    assert len(result.evidence) == 2
    assert result.completion["investigation"] == "completed"
    assert result.completion["accounted_observations"] == 2
    assert not result.unresolved
    assert [event.interval for event in result.timeline] == [
        Interval(1_000_000, 2_000_001), Interval(5_000_000, 6_000_001),
    ]
    assert "00:05.000000–00:06.000000" in result.report
    assert result.ask("When did the object disappear?").events == result.timeline[1:]
    assert not result.ask("Did anyone remove the object?").events

    cases = [
        ("What visual changes occurred in the video?", result.timeline),
        ("What appeared in the video?", result.timeline[:1]),
        ("When did the object disappear?", result.timeline[1:]),
        ("What happened between 1 and 3 seconds?", result.timeline[:1]),
        ("Did someone physically place the object?", ()),
        ("Did a person enter the scene?", ()),
        ("What happened between 7.2 and 7.8 seconds?", ()),
    ]
    outcomes = [result.ask(question) for question, _ in cases]
    assert [answer.events for answer in outcomes] == [expected for _, expected in cases]
    assert "00:05.000000–00:06.000000" in outcomes[2].text
    assert "became visible" in outcomes[4].text and "does not establish physical placement" in outcomes[4].text
    assert "does not establish absence" in outcomes[5].text
    assert "no inspected evidence" in outcomes[6].text.lower()
    bracket_gap = result.ask("What happened between 1.2 and 1.8 seconds?")
    assert bracket_gap.events == result.timeline[:1]
    assert "exact time within its bracket is unknown" in bracket_gap.text


def test_verification_wire_schema_enforces_transition_for_recorded_movement_support(monkeypatch):
    import json
    from pathlib import Path

    import httpx
    from google import genai
    from jsonschema import Draft202012Validator

    from security_augmented.agents import AgentModels, GeminiDecider
    from security_augmented.gemini import GeminiAdapter

    archive = (Path(__file__).resolve().parents[1] / "experiments/meet_walk_split_high_probes"
               / "independent-relational-tasks-retry-live/result.json")
    run = json.loads(archive.read_text())
    verdicts = [row for row in run["decisions"]
                if row["role"] == "verification" and row["decision"].get("verdict") == "supported"]
    captured = []
    rows = iter(verdicts)

    def respond(request):
        captured.append(json.loads(request.content))
        row = next(rows)
        return httpx.Response(200, json={"candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(row["decision"])}]}}
        ]})

    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    with genai.Client(api_key="offline", vertexai=False, http_options={
        "client_args": {"transport": httpx.MockTransport(respond)},
    }) as client:
        decider = GeminiDecider(GeminiAdapter(client=client), AgentModels(**run["models"]))
        for row in verdicts:
            assert decider("verification", row["context"]) == row["decision"]

    missing = 0
    for row, body in zip(verdicts, captured, strict=True):
        assert json.loads(body["contents"][0]["parts"][0]["text"]) == row["context"]
        schema = Draft202012Validator(body["generationConfig"]["responseJsonSchema"])
        decision = row["decision"]
        paired = "transition" in decision
        assert schema.is_valid(decision) == paired
        missing += int(not paired)
        for status in ("unsupported", "insufficient"):
            uncertain = {**decision, "verdict": status}
            uncertain.pop("transition", None)
            assert schema.is_valid(uncertain)
    assert missing == 5 and len(verdicts) == 7
