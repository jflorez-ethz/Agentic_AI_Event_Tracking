from dataclasses import replace
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph")

from security_augmented.contracts import Interval, VideoError
from security_augmented.workflow import ArchivedInspection, Budget, _analyze
from test_evidence_semantics import finding


@pytest.mark.parametrize(("mode", "expected_completed", "expected_calls", "expected_tools"), [
    ("recover", 3, 9, 2),
    ("exhaust", 2, 7, 1),
    ("budget", 0, 5, 1),
    ("api", 0, 5, 1),
])
def test_rejected_inspection_recovery_and_candidate_isolation(mode, expected_completed, expected_calls, expected_tools):
    seeds = tuple(finding(i, "person_enters_area", "A person crosses the door threshold.", times)
                  for i, times in (("a", (10, 20)), ("b", (40, 50)), ("c", (60, 70))))
    initial = (ArchivedInspection("fixture", "frames", Interval(0, 100), "success", seeds),)
    budget = Budget(max_candidates=3, max_inspections=2, max_agent_calls=5 if mode == "budget" else 9,
                    max_verification_iterations=5, max_recoveries=1 if mode == "exhaust" else 2, max_failures=1)
    inspect = {"action": "inspect", "modality": "frames", "start_us": 10, "end_us": 21}
    calls = []
    requests = []
    first = iter([
        {"action": "verdict", "verdict": "supported", "ids": ["a"], "correspondence": []},
        inspect, inspect,
    ])

    def observe(interval, modality):
        requests.append((interval, modality))
        findings = ()
        if modality == "clip":
            corroborating = finding("corroborating", "person_enters_area", "A person crosses the door threshold.", (10, 15, 20))
            findings = (replace(corroborating, citation=replace(corroborating.citation, modality="clip")),)
        return (ArchivedInspection("fixture", modality, interval, "success", findings, coverage=(interval,)),)

    def decide(role, context):
        calls.append((role, context))
        if role == "investigation":
            action = {"action": "delegate", "ids": ["a", "b", "c"], "dispositions": []}
        elif role == "reporting":
            action = {"action": "report", "lead_id": None, "emphasis": "uncertainty"}
        else:
            identifier = context["candidate_id"]
            feedback = context.get("validation_feedback", {})
            if identifier != "a":
                assert not feedback
            action = {"action": "verdict", "verdict": "insufficient", "ids": [identifier], "correspondence": []}
            if identifier == "a":
                if feedback.get("code") == "inspection_repeated" and len(requests) == 1:
                    assert feedback["requested"] == {"modality": "frames", "start_us": 10, "end_us": 21}
                    if mode == "api":
                        raise VideoError("Mock provider failure")
                    action = dict(inspect, modality="clip")
                elif feedback.get("code") == "inspection_repeated" and "corroborating" in context["evidence"]:
                    action = {"action": "verdict", "verdict": "supported", "ids": ["a", "corroborating"], "boundary": "door threshold",
                              "correspondence": [{
                                  "id": "corroborating", "status": "same_event", "seed_quote": "crosses the door threshold",
                                  "other_quote": "crosses the door threshold", "shared_frame_id": "frame-10",
                              }]}
                elif feedback.get("code") != "inspection_repeated":
                    action = next(first)
        return {**action, "reason": "Scripted decision."}

    result = _analyze(SimpleNamespace(id="video", sha256="hash", duration_us=100), initial, observe,
                      budget, decide=decide, controller="langgraph")
    assert len(calls) == expected_calls
    assert len(requests) == expected_tools
    assert len(result.timeline) == (1 if mode == "recover" else 0)
    assert len(result.unresolved) + len(result.timeline) == 3
    assert result.completion["investigation"] == ("completed" if mode == "recover" else "partial")
    assert result.completion["completed_checks"] == expected_completed
    assert f"{expected_completed}/3 checks completed" in result.report
    verdicts = [d.details for d in result.trace if d.action == "verdict"]
    assert [v["candidate_id"] for v in verdicts] == ["a", "b", "c"]
    assert any(d.action == "evidence_insufficient" for d in result.trace)
    assert any(d.action == "inspection_rejected" for d in result.trace)
    assert any(d.action == "model_failure" for d in result.trace) == (mode == "api")
