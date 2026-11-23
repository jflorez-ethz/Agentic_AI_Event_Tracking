from types import SimpleNamespace
from dataclasses import replace

import pytest

from security_augmented.agents import AgentRun
from security_augmented.contracts import VideoError
from security_augmented.evidence import CorroborationRequired
from security_augmented.workflow import Budget
from test_evidence_semantics import finding


def evidence(identifier, times, description):
    item = finding(identifier, "person_enters_area", description, times)
    return replace(item, citation=replace(item.citation, frames=tuple(
        replace(f, rgb24_sha256=f.id) for f in item.citation.frames
    )))


def run():
    return AgentRun(SimpleNamespace(duration_us=100, id="video", sha256="hash"), None, None, Budget(), [])


@pytest.mark.parametrize("category", ["person_appeared", "person_moved"])
def test_explicit_narrowing_uses_cited_ordered_frames(category):
    seed = evidence("seed", (10, 20), "Person comes into view near the image edge.")
    agent = run()
    action = {"verdict": "supported", "ids": ["seed"], "reason": "Observed change.",
              "refinement": {"category": category, "observation_id": "seed",
                             "before_frame_id": "frame-10", "after_frame_id": "frame-20"}}
    event = agent.finish_verification(seed, {"seed": seed}, *agent.verdict(seed, action, {"seed": seed}), completed=True)
    assert event.category == category
    assert event.interval == seed.citation.interval
    assert event.citations == (seed.citation,)
    with pytest.raises(VideoError):
        agent.verdict(seed, {**action, "refinement": {**action["refinement"], "after_frame_id": "unknown"}}, {"seed": seed})


@pytest.mark.parametrize(("boundary", "supported"), [(None, False), ("door threshold", True), ("image edge", False), ("top right", False)])
def test_entry_requires_named_grounded_physical_boundary(boundary, supported):
    label = boundary or "door threshold"
    description = f"A person crosses the {label} into the hall."
    seed = evidence("seed", (10, 20), description)
    other = evidence("other", (10, 15, 20), description)
    action = {"verdict": "supported", "ids": ["seed", "other"], "reason": "Crossing observed.",
              "correspondence": [{"id": "other", "status": "same_event", "seed_quote": description,
                                  "other_quote": description, "shared_frame_id": "frame-10"}]}
    if boundary is not None:
        action["boundary"] = boundary
    if supported:
        assert run().verdict(seed, action, {"seed": seed, "other": other})[1] == "supported"
    else:
        with pytest.raises(CorroborationRequired):
            run().verdict(seed, action, {"seed": seed, "other": other})


@pytest.mark.parametrize("separate", [False, True])
def test_person_passages_preserve_grounded_triage_without_time_based_merging(separate):
    pytest.importorskip("langgraph")
    from security_augmented.workflow import ArchivedInspection, _analyze
    from security_augmented.contracts import Interval

    a = evidence("a", (10, 20), "First visibility near the top edge.")
    b = (
        evidence("b", (40, 50), "After the first person has left, another person moves from the opposite side.")
        if separate else evidence("b", (20, 30), "A figure continues moving from the top edge.")
    )
    def decide(role, context):
        if role == "investigation":
            if separate:
                return {"action": "delegate", "ids": ["a", "b"], "dispositions": [], "reason": "Scripted separate passages."}
            return {"action": "delegate", "ids": ["a"], "reason": "One passage to verify.", "dispositions": [{
                "id": "b", "status": "associated", "candidate_id": "a", "reason": "Continuation.",
                "correspondence": {"id": "b", "status": "same_event", "seed_quote": "top edge",
                                   "other_quote": "top edge", "shared_frame_id": "frame-20"},
            }]}
        if role == "reporting":
            return {"action": "report", "lead_id": None, "emphasis": "uncertainty", "reason": "Summarize."}
        identifier = context["candidate_id"]
        before, after = (10, 20) if identifier == "a" else (40, 50)
        return {"action": "verdict", "verdict": "supported", "ids": [identifier], "correspondence": [],
                "reason": "Scripted visible change.", "refinement": {
                    "category": "person_appeared" if identifier == "a" else "person_moved",
                    "observation_id": identifier, "before_frame_id": f"frame-{before}", "after_frame_id": f"frame-{after}",
                }}

    result = _analyze(
        run().video, (ArchivedInspection("local", "frames", Interval(0, 100), "success", (a, b)),),
        lambda *_: (), Budget(), decide=decide, controller="langgraph",
    )
    assert len(result.timeline) == (2 if separate else 1)
    assert result.completion["accounted_observations"] == 2
    assert len(result.unresolved) == (0 if separate else 1)
    if separate:
        assert result.timeline[0].interval.end_us < result.timeline[1].interval.start_us
    else:
        assert result.unresolved[0].observation_ids == ("b",)
    assert not result.ask("Did a person enter the scene?").events
