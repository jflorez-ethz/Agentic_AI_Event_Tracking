"""Operator review queue (plan p. 8, Guardrails), replayed offline on archived live runs."""
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from security_augmented.review import render, review
from security_augmented.workflow import Analysis

ROOT = Path(__file__).resolve().parents[1] / "experiments"


def load(run):
    return TypeAdapter(Analysis).validate_python(json.loads((ROOT / run / "analysis.json").read_text())["analysis"])


def queue(analysis):
    return review(analysis.timeline + analysis.unresolved, analysis.trace, analysis.evidence)


def test_leftbox_box_is_an_alert_with_short_frame_selection_and_no_routine_alerts():
    analysis = load("leftbox_live.1iXjTj/run")
    result = queue(analysis)
    (alert,) = result["alerts"]
    assert (alert["status"], alert["category"]) == ("needs_review", "object_placed")
    assert alert["reason_code"] == "inspection_rejected/no_new_frames"
    assert alert["cited_frame_count"] == 20
    # First, last and the frames named in the description (F1-F5, F6-F7, F8-F20), capped at six.
    assert [f["label"] for f in alert["frames"]] == ["F1", "F5", "F6", "F7", "F8", "F20"]
    assert [f["display_index"] for f in alert["frames"]][2:4] == [557, 569]  # set down at 22.52-23.00 s
    assert alert["operator_label"] is None and alert["id"].startswith("alert-")
    assert not any(a["category"] in ("person_moved", "person_appeared") for a in result["alerts"])
    assert result["counts"] == {"needs_review": 1, "supported_security": 0, "unclear": 0,
                                "not_alerted": {"zone_undefined": 0, "contradicted": 0}}
    text = render(result)
    assert text.startswith("## Alertes à vérifier (1)")
    assert "Objet déposé" in text and "6 sur 20 images citées" in text and "Question :" in text


def test_alert_is_never_evidence():
    analysis = load("leftbox_live.1iXjTj/run")
    assert queue(analysis)["alerts"]
    assert not any(e.category == "object_placed" for e in analysis.timeline)
    assert not analysis.ask("Was an object placed?").events


@pytest.mark.parametrize(("run", "codes", "counts"), [
    ("leftbox_live.qyrM8F/run", ["not_checked"], (1, 0, 0, 0)),
    ("leftbox_live.HwKyEx/run", [], (0, 1, 0, 0)),          # box confirmed after the rejection recovery
    ("fall_live.spFaYl/run", [], (0, 1, 0, 0)),             # fall confirmed
    ("meet_walk_recovery.50raLm/run", [], (0, 0, 3, 0)),    # entries: no monitored zone configured
    ("meet_walk_pts_budget14.VxoEyL/run", [], (0, 0, 3, 0)),
    ("meet_walk_pts_20261122_013252", [], (0, 0, 2, 0)),
    ("meet_walk_split_500ms.bqVoWC/run", [], (0, 0, 0, 1)),  # fixed case present from F1, contradicted
])
def test_archived_runs_match_the_step_zero_simulation(run, codes, counts):
    result = queue(load(run))
    assert [a["reason_code"] for a in result["alerts"]] == codes
    c = result["counts"]
    assert (c["needs_review"], c["supported_security"], c["not_alerted"]["zone_undefined"],
            c["not_alerted"]["contradicted"]) == counts


def test_contradicted_fall_is_never_dismissed():
    analysis = load("leftbox_live.1iXjTj/run")
    (box,) = [e for e in analysis.unresolved if e.category == "object_placed"]
    fall = replace(box, category="person_fell", verdict="unsupported", reason="The frames do not show a fall.")
    result = review((fall,), analysis.trace, analysis.evidence)
    (alert,) = result["alerts"]
    assert (alert["category"], alert["reason_code"]) == ("person_fell", "contradicted")
    contradicted_object = replace(box, verdict="unsupported", reason="The frames show no placement.")
    assert not review((contradicted_object,), analysis.trace, analysis.evidence)["alerts"]


def test_unfinished_and_affirmative_reason_flag():
    analysis = load("leftbox_live.1iXjTj/run")
    (box,) = [e for e in analysis.unresolved if e.category == "object_placed"]
    stopped = replace(box, reason="Verification iteration limit reached.")
    assert review((stopped,), analysis.trace, analysis.evidence)["alerts"][0]["reason_code"] == "unfinished"
    odd = replace(box, reason="The cited frames establish the placement of the box.")
    (alert,) = review((odd,), (), analysis.evidence)["alerts"]
    assert alert["model_reason_affirmative"] and "paraît affirmatif" in render({"alerts": [alert], "not_alerted": []})


def test_end_to_end_report_starts_with_alerts(tmp_path):
    pytest.importorskip("langgraph")
    from security_augmented.contracts import Interval
    from security_augmented.observation import FrameReference, InferenceMetadata, Observation, ObservationResult
    from security_augmented.workflow import Budget, InspectionPlan, analyze_video
    from test_new_video import make_video

    path = tmp_path / "block.mkv"
    make_video(path)

    class Provider:
        def infer(self, request):
            inspection = request.media.inspection
            meta = InferenceMetadata("offline", "mock", None, "1", "1")
            if inspection.requested_interval == Interval(0, 4_000_000):
                cited = [f for f in inspection.frames if f.source_time_us in (1_500_000, 2_000_000, 2_500_000)]
                return ObservationResult(meta, (
                    Observation("placed", inspection.id, "object_placed", "A block is set down in F4-F6.",
                                FrameReference(tuple(f.id for f in cited)), "Fixed view.", "Actor not visible."),
                    Observation("walk", inspection.id, "person_moved", "A person walks in F4-F6.",
                                FrameReference(tuple(f.id for f in cited)), "Fixed view.", "None."),))
            return ObservationResult(meta, ())

    def decide(role, context):
        if role == "investigation":
            return {"action": "delegate", "ids": list(context["evidence"]), "dispositions": [], "reason": "Check."}
        if role == "reporting":
            return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
        seed = context["candidate_id"]
        return {"action": "verdict", "verdict": "insufficient", "ids": [seed], "correspondence": [],
                "reason": "Not enough to confirm."}

    result = analyze_video(path, Provider(), decide=decide, controller="langgraph",
                           plan=InspectionPlan(window_us=4_000_000, frame_step_us=500_000),
                           budget=Budget(max_initial_windows=2, max_candidates=2, max_inspections=0,
                                         max_agent_calls=6, max_verification_iterations=2))
    assert result.report.startswith("## Alertes à vérifier (1)")
    assert result.report.index("## Alertes à vérifier") < result.report.index("# Video investigation")
    (alert,) = result.review["alerts"]
    assert alert["category"] == "object_placed" and alert["reason_code"] == "missing_corroboration"
    assert result.review["counts"]["needs_review"] == 1
