"""A pre-dispatch inspection rejection gets its own feedback round (live LeftBox run leftbox_live.1iXjTj)."""
import json

import httpx
import pytest

from security_augmented.contracts import Interval
from security_augmented.observation import FrameReference, InferenceMetadata, Observation, ObservationResult
from security_augmented.workflow import Budget, InspectionPlan, analyze_video
from test_new_video import make_video


def test_no_new_frames_rejection_leads_to_a_fine_corroborating_inspection(tmp_path):
    pytest.importorskip("langgraph")
    path = tmp_path / "block.mkv"
    make_video(path)
    requests = []

    class Provider:
        def infer(self, request):
            inspection = request.media.inspection
            requests.append(inspection)
            meta = InferenceMetadata("offline", "mock", None, "1", "1")
            if inspection.requested_interval == Interval(0, 4_000_000):
                cited = [f for f in inspection.frames if f.source_time_us in (1_500_000, 2_000_000, 2_500_000)]
                return ObservationResult(meta, (Observation(
                    "placed", inspection.id, "object_placed", "A block is set down on the floor.",
                    FrameReference(tuple(f.id for f in cited)), "Fixed view.", "Actor not visible."),))
            return ObservationResult(meta, ())

    verification = []

    def decide(role, context):
        if role == "investigation":
            return {"action": "delegate", "ids": list(context["evidence"]), "dispositions": [], "reason": "Check it."}
        if role == "reporting":
            return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
        verification.append(context)
        seed = context["candidate_id"]
        cited = context["evidence"][seed]["interval"]
        step = len(verification)
        if step == 1:  # live: supported without corroboration
            return {"action": "verdict", "verdict": "supported", "ids": [seed], "correspondence": [],
                    "reason": "The block is placed."}
        if step == 2:  # live: default-rate inspection of the already sampled span
            return {"action": "inspect", "modality": "frames", "start_us": cited["start_us"],
                    "end_us": cited["end_us"], "reason": "Corroborate the placement."}
        if step == 3:
            return {"action": "inspect", "modality": "frames", "start_us": 1_000_000, "end_us": 3_000_000,
                    "sampling_step_ms": 250, "visual_question": "When does the block first rest on the floor?",
                    "reason": "Finer frames between existing samples."}
        return {"action": "verdict", "verdict": "insufficient", "ids": [seed], "correspondence": [],
                "reason": "No corroborating description."}

    result = analyze_video(
        path, Provider(), decide=decide, controller="langgraph",
        plan=InspectionPlan(window_us=4_000_000, frame_step_us=500_000),
        budget=Budget(max_initial_windows=2, max_candidates=1, max_inspections=2, max_agent_calls=10,
                      max_verification_iterations=4),
    )
    assert len(verification) == 4
    assert all(c["new_frames_at_500ms_in_citation"] is False for c in verification)
    feedback = verification[2]["validation_feedback"]
    assert feedback["code"] == "no_new_frames" and "sampling_step_ms=250" in feedback["guidance"]
    assert verification[1]["validation_feedback"]["code"] == "missing_corroboration"
    targeted = [r for r in requests if r.requested_interval == Interval(1_000_000, 3_000_000)]
    assert len(targeted) == 1 and len(targeted[0].frames) > 0
    actions = [t.action for t in result.trace if t.actor == "verification"]
    assert actions.count("recovery") == 2 and "inspection_rejected" in actions


def test_rejection_round_does_not_extend_the_evidence_recovery_budget(tmp_path):
    """A second rejection (no rejection recoveries left) still ends the check, as before."""
    pytest.importorskip("langgraph")
    path = tmp_path / "block.mkv"
    make_video(path)

    class Provider:
        def infer(self, request):
            inspection = request.media.inspection
            meta = InferenceMetadata("offline", "mock", None, "1", "1")
            if inspection.requested_interval == Interval(0, 4_000_000):
                cited = [f for f in inspection.frames if f.source_time_us in (1_500_000, 2_000_000, 2_500_000)]
                return ObservationResult(meta, (Observation(
                    "placed", inspection.id, "object_placed", "A block is set down.",
                    FrameReference(tuple(f.id for f in cited)), "Fixed view.", "Actor not visible."),))
            return ObservationResult(meta, ())

    calls = []

    def decide(role, context):
        if role == "investigation":
            return {"action": "delegate", "ids": list(context["evidence"]), "dispositions": [], "reason": "Check."}
        if role == "reporting":
            return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
        calls.append(context)
        cited = context["evidence"][context["candidate_id"]]["interval"]
        return {"action": "inspect", "modality": "frames", "start_us": cited["start_us"],
                "end_us": cited["end_us"], "reason": "Same grid again."}

    result = analyze_video(
        path, Provider(), decide=decide, controller="langgraph",
        plan=InspectionPlan(window_us=4_000_000, frame_step_us=500_000),
        budget=Budget(max_initial_windows=2, max_candidates=1, max_inspections=2, max_agent_calls=10,
                      max_verification_iterations=4),
    )
    assert len(calls) == 2
    (event,) = result.unresolved
    assert event.verdict == "insufficient" and "adds no source frames" in event.reason


def test_role_call_archives_the_returned_decision(monkeypatch):
    from security_augmented.agents import AgentModels, GeminiDecider, RoleHTTPBudget
    from security_augmented.gemini import GeminiAdapter

    monkeypatch.setenv("GEMINI_API_KEY", "offline")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    decision = {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
    texts = iter([json.dumps(decision), "not json"])

    def respond(request):
        return httpx.Response(200, json={"modelVersion": "m", "usageMetadata": {"promptTokenCount": 1},
                                         "candidates": [{"finishReason": "STOP",
                                                         "content": {"parts": [{"text": next(texts)}]}}]})

    budget = RoleHTTPBudget(4, media_limit=0)
    adapter = GeminiAdapter.from_env(authorized=True, model="m", single_request=True, client_args={
        "transport": httpx.MockTransport(respond),
        "event_hooks": {"request": [budget.before_send], "response": [budget.after_response]}})
    model = GeminiDecider(adapter, AgentModels("m", "m", "m", "m"), http_budget=budget)
    context = {"evidence": {}}
    with adapter.client:
        assert model("reporting", context) == decision
        with pytest.raises(Exception, match="JSON"):
            model("reporting", context)
    assert model.calls[0]["decision"] == decision
    assert model.calls[1]["raw_text"] == "not json" and "decision" not in model.calls[1]
