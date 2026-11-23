from types import SimpleNamespace

import pytest

from security_augmented.agents import AgentRun
from security_augmented.contracts import VideoError
from security_augmented.workflow import Budget
from test_evidence_semantics import finding


def pair(identifier, *, shared="frame-10", other_quote="red bag"):
    return {"id": identifier, "status": "same_event", "seed_quote": "red bag",
            "other_quote": other_quote, "shared_frame_id": shared}


@pytest.mark.parametrize("mode", ["omitted", "excluded", "deferred", "associated", "resolved", "invalid", "distinct"])
def test_triage_and_verification_completion_are_distinct(mode):
    seed = finding("seed", "object_placed", "A person places a red bag.", (10, 20))
    ambiguous = finding(
        "other", "insufficient_evidence",
        {"distinct": "A blue box is lifted.", "excluded": "A light flickers."}.get(mode, "A red bag is handled."),
        (10, 17),
    )
    later = finding("later", "object_placed", "The red bag is set down.", (10, 19))
    record = {"id": "other", "status": mode, "reason": (
        "The light flicker is outside the object-handling scope." if mode == "excluded" else "Synthetic assessment."
    )}
    if mode in {"associated", "resolved", "invalid"}:
        record.update(status="associated", candidate_id="seed",
                      correspondence=pair("other", shared="bad" if mode == "invalid" else "frame-10"))
    if mode == "distinct":
        record.update(status="associated", candidate_id="seed", correspondence={
            **pair("other", shared=None, other_quote="blue box"), "status": "different_events",
        })
    run = AgentRun(
        SimpleNamespace(duration_us=100, id="video", sha256="hash"),
        lambda *_: {"action": "delegate", "ids": ["seed"], "reason": "Review placement.",
                    "dispositions": [] if mode == "omitted" else [record]},
        None, Budget(max_failures=1), [],
    )
    candidates = run.investigate((seed, ambiguous))
    if mode in {"invalid", "distinct"}:
        assert candidates == []
        assert run.completion()["accounted_observations"] == 0
        return
    assert candidates == [seed]
    visible = run.visible_for(seed, shared={"later": later})
    action = {"verdict": "supported", "ids": ["seed", "later"], "reason": "Corroborated.",
              "correspondence": [pair("later")]}
    if mode == "resolved":
        with pytest.raises(VideoError):
            run.verdict(seed, {
                **action, "resolutions": [{"id": "other", "correspondence": pair("later", shared="frame-20")}],
            }, visible)
        assert not run.resolved_associations
        action["resolutions"] = [{"id": "other", "correspondence": pair("later")}]
    result = run.finish_verification(seed, visible, *run.verdict(seed, action, visible), completed=True)
    events = run.finalize_events((result,))
    completion = run.completion()
    assert completion["verification"] == "completed"
    assert completion["accounted_observations"] == (1 if mode == "omitted" else 2)
    assert completion["investigation"] == ("completed" if mode in {"excluded", "resolved"} else "partial")
    assert {e.observation_ids[0] for e in events if e.verdict != "supported"} == (
        set() if mode in {"excluded", "resolved"} else {"other"}
    )
    run.decide = lambda *_: {"action": "report", "lead_id": "seed", "emphasis": "evidence", "reason": "Report fixture."}
    report = run.report(events)
    assert f"Investigation: {completion['investigation']}" in report
    assert "An object was placed" in report
    if mode == "resolved":
        assert "Associated observations resolved by corroborating evidence: 1" in report
        assert any(d.action == "association_resolved" and d.observation_ids == ("other", "later") for d in run.trace)


def test_failure_before_triage_preserves_initial_evidence():
    initial = finding("other", "insufficient_evidence", "Ambiguous handling.", (10, 17))

    def fail(*_):
        raise VideoError("Offline test failure")

    run = AgentRun(SimpleNamespace(duration_us=100), fail, None, Budget(), [])
    assert run.investigate((initial,)) == []
    assert run.completion()["investigation"] == "failed"
    assert run.completion()["accounted_observations"] == 0
    assert run.finalize_events(())[0].citations == (initial.citation,)
