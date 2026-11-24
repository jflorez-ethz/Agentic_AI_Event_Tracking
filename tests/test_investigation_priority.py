"""Investigation must check security-relevant observations before routine person activity.

Replays the archived Investigation triage of the live LeftBox and Rest_FallOnFloor runs
(2026-11-23) through the current runtime. No media or provider call is involved.
"""
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from security_augmented.agents import AgentRun
from security_augmented.workflow import Analysis, Budget, Finding

ROOT = Path(__file__).resolve().parents[1]
LEFTBOX = ROOT / "experiments/leftbox_live.qyrM8F/run/analysis.json"
FALL = ROOT / "experiments/fall_live.spFaYl/run/analysis.json"


def archived(path):
    data = json.loads(path.read_text())["analysis"]
    analysis = TypeAdapter(Analysis).validate_python(data)
    rows = data["completion"]["observation_dispositions"]
    delegation = {
        "action": "delegate", "reason": "Archived live triage.",
        "ids": [r["id"] for r in rows if r["status"] == "delegated"],
        "dispositions": [{k: r[k] for k in ("id", "status", "reason")} for r in rows if r["status"] != "delegated"],
    }
    return analysis, delegation


def by_category(analysis, category):
    return [f.observation.id for f in analysis.observations if f.observation.category == category]


def scripted(*decisions):
    contexts = []

    def decide(role, context):
        assert role == "investigation"
        contexts.append(context)
        return decisions[min(len(contexts), len(decisions)) - 1]
    return decide, contexts


def run_for(analysis, decide, **budget):
    trace = []
    run = AgentRun(analysis.video, decide, None, Budget(**{"max_candidates": 4, "max_agent_calls": 14, **budget}), trace)
    picks = run.investigate(analysis.observations)
    return run, [f.observation.id for f in picks], trace


def test_archived_leftbox_triage_is_returned_with_feedback_and_corrected():
    analysis, delegation = archived(LEFTBOX)
    (box,) = by_category(analysis, "object_placed")
    moved = by_category(analysis, "person_moved")
    assert box not in delegation["ids"] and sorted(delegation["ids"]) == sorted(moved)  # the live failure
    corrected = {
        "action": "delegate", "reason": "Security first.", "ids": [box, *moved[:3]],
        "dispositions": [*(d for d in delegation["dispositions"] if d["id"] != box),
                         {"id": moved[3], "status": "deferred", "reason": "Routine; budget used."}],
    }
    decide, contexts = scripted(delegation, corrected)
    run, picks, trace = run_for(analysis, decide)
    assert len(contexts) == 2
    feedback = contexts[1]["last_tool_result"]
    assert feedback["code"] == "priority_observations_not_delegated" and feedback["priority_ids"] == [box]
    assert picks == [box, *moved[:3]]
    assert run.dispositions[box]["status"] == "delegated"
    assert not any(t.action == "priority_enforced" for t in trace)


def test_repeated_violation_is_enforced_without_losing_checks():
    analysis, delegation = archived(LEFTBOX)
    (box,) = by_category(analysis, "object_placed")
    decide, contexts = scripted(delegation)  # Investigation repeats the same triage after feedback
    run, picks, trace = run_for(analysis, decide)
    assert len(contexts) == 2 and len(picks) == 4
    assert box in picks
    displaced = [i for i in delegation["ids"] if i not in picks]
    assert len(displaced) == 1
    assert run.dispositions[displaced[0]] == {
        "id": displaced[0], "status": "deferred", "reason": "Displaced by the runtime security-priority rule."}
    (enforced,) = [t for t in trace if t.action == "priority_enforced"]
    assert enforced.details["displaced"] == displaced


def test_no_feedback_round_when_calls_are_short():
    analysis, delegation = archived(LEFTBOX)
    (box,) = by_category(analysis, "object_placed")
    decide, contexts = scripted(delegation)
    _, picks, _ = run_for(analysis, decide, max_agent_calls=3)
    assert len(contexts) == 1 and box in picks


def test_compliant_triage_is_untouched():
    analysis, delegation = archived(FALL)
    (fall,) = by_category(analysis, "person_fell")
    assert fall in delegation["ids"]  # person_fell was delegated live; routine slots then remain free to use
    decide, contexts = scripted(delegation)
    run, picks, trace = run_for(analysis, decide)
    assert len(contexts) == 1 and picks == [f.observation.id for f in analysis.observations if f.observation.id in delegation["ids"]]
    assert not any(t.action in ("recovery", "priority_enforced") for t in trace)


def test_priority_beyond_candidate_budget_does_not_force_routine_out():
    analysis, delegation = archived(LEFTBOX)
    (box,) = by_category(analysis, "object_placed")
    only_box = {"action": "delegate", "reason": "One slot.", "ids": [box], "dispositions": [
        {"id": f.observation.id, "status": "deferred", "reason": "Budget."}
        for f in analysis.observations if f.observation.id != box]}
    decide, contexts = scripted(only_box)
    _, picks, _ = run_for(analysis, decide, max_candidates=1)
    assert len(contexts) == 1 and picks == [box]


def test_late_priority_observation_stays_visible_to_investigation():
    analysis, _ = archived(LEFTBOX)
    (box,) = by_category(analysis, "object_placed")
    routine = [f for f in analysis.observations if f.observation.id != box]
    extra = [Finding(replace(f.observation, id=f"{f.observation.id}-copy{n}-{k}"), f.citation)
             for k in range(2) for n, f in enumerate(routine)]
    ordered = [*routine, *extra, next(f for f in analysis.observations if f.observation.id == box)]
    assert len(ordered) == 22 and ordered[-1].observation.id == box
    seen = []

    def decide(role, context):
        seen.append(context)
        return None
    run = AgentRun(analysis.video, decide, None,
                   Budget(max_candidates=4, max_agent_calls=14, max_visible_observations=16), [])
    run.investigate(tuple(ordered))
    evidence = seen[0]["evidence"]
    assert len(evidence) == 16 and box in evidence  # max_visible_observations
    assert list(evidence)[:15] == [f.observation.id for f in ordered[:15]]  # routine fill stays chronological
    assert seen[0]["additional_evidence_available"] is True
