"""Regression for the distinct unresolved outcomes observed in mvp_live.UAJd48."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from security_augmented.agents import AgentRun
from security_augmented.graph_workflow import run_graph
from security_augmented.workflow import Analysis


def test_rejected_skipped_and_deferred_have_distinct_reasons():
    path = Path(__file__).resolve().parents[1] / "experiments/mvp_live.UAJd48/run/analysis.json"
    archived = TypeAdapter(Analysis).validate_python(json.loads(path.read_text())["analysis"])
    dispositions = archived.completion["observation_dispositions"]
    delegated = [row["id"] for row in dispositions if row["status"] == "delegated"]
    pair = next(d.details for d in archived.trace if d.action == "transition_evidence")
    transition = {k: pair[k] for k in ("observation_id", "before_frame_id", "after_frame_id")}

    def decide(role, context):
        if role == "investigation":
            return {"action": "delegate", "ids": delegated, "reason": "Check movements.",
                    "dispositions": [row for row in dispositions if row["status"] == "deferred"]}
        assert role == "verification"
        seed = context["candidate_id"]
        decision = {"action": "verdict", "reason": "Evaluate the cited movement.",
                    "ids": [seed], "correspondence": []}
        if seed == delegated[0]:
            return decision | {"verdict": "supported", "transition": transition}
        if seed == delegated[1]:
            return decision | {"verdict": "unsupported"}
        assert seed == delegated[2]
        # The original invalid JSON object is unavailable. Exercise the same guard.
        return decision | {"verdict": "unsupported", "unexpected": "fixture"}

    run = AgentRun(archived.video, decide, None, archived.budget, [], initial_scan="completed")
    events, report = run_graph(run, archived.observations)
    assert run.completion()["completed_checks"] == 2
    assert [e.verdict for e in events] == ["supported", "unsupported", "insufficient", "insufficient", "insufficient"]
    rejected, = [d for d in run.trace if d.action == "rejected"]
    assert rejected.details["candidate_id"] == delegated[2]
    assert rejected.details["unexpected_fields"] == ["unexpected"]
    for reason in ("Malformed decision or unavailable action.", "Execution failure limit reached.",
                   "Observation deferred during triage."):
        assert reason in report
    assert "A source-grounded before/after pair was not established." not in report
    assert events[0].citations == archived.timeline[0].citations


def test_fine_allowance_belongs_to_the_task_and_frame_novelty_is_shared():
    from dataclasses import replace

    import pytest

    from security_augmented.agents import InspectionRejected
    from security_augmented.video import sample
    from security_augmented.workflow import _coverage

    path = Path(__file__).resolve().parents[1] / "experiments/mvp_live.UAJd48/run/analysis.json"
    archived = TypeAdapter(Analysis).validate_python(json.loads(path.read_text())["analysis"])
    left, right = archived.observations[1:3]
    visible = {f.observation.id: f for f in (left, right)}
    source = replace(archived.video, source_path=str(path.parents[3] / "data/raw/Meet_WalkSplit_pts.mp4"))
    indices = {f.display_index for e in archived.evidence for f in e.inspection.frames}
    requests = []

    def inspect(interval, modality, *, sampling_step_ms, visual_question, relational=False):
        requests.append((interval, relational))
        frames = sample(source, interval, list(range(interval.start_us, interval.end_us, sampling_step_ms * 1000)))
        return [replace(archived.evidence[0], inspection=frames, interval=interval, findings=(), phase="targeted",
                        coverage=_coverage(frames))]

    question = {"action": "inspect", "modality": "frames", "sampling_step_ms": 250, "start_us": 4_000_000,
                "end_us": 5_000_000, "reason": "Timing is ambiguous.", "visual_question": "Which positions change?"}
    def decide(role, context):
        return question | ({"relational": True} if "relational_task" in context else {})

    run = AgentRun(source, decide, inspect, archived.budget, [],
                   sampled_indices=indices, autonomous_relations=True, relational_selection=True)
    run.dispositions = {k: {"status": "deferred"} for k in visible}
    task, = run._relation_delegations([{"observation_ids": list(visible)}], visible, run.dispositions, 1)
    run.verification_action(left, visible, 0, None)
    assert run.reinspect(left, question, visible)["new_display_indices"] == [107, 119]
    followup = {**question, "start_us": 5_000_000, "end_us": 6_000_000}
    with pytest.raises(InspectionRejected) as exc:
        run.reinspect(left, followup, visible)
    assert exc.value.code == "fine_limit"
    run.verification_action(left, visible, 0, None, task=task)
    redundant = {**question, "relational": True, "start_us": 3_999_999}
    with pytest.raises(InspectionRejected) as exc:
        run.reinspect(left, redundant, visible, task=task)
    assert exc.value.code == "no_new_frames"
    result = run.reinspect(left, {**followup, "relational": True}, visible, task=task)
    assert result["new_display_indices"] == [132, 144]
    assert [relational for _, relational in requests] == [False, True]
    assert run.fine_tasks == {left.observation.id, task.id}
