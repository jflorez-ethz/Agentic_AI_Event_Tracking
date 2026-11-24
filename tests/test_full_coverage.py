"""Whole-video initial scan and before/after context for placement and removal checks."""
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from security_augmented.agents import AgentRun, InspectionRejected, inspection_scope
from security_augmented.contracts import Interval, VideoError
from security_augmented.workflow import MAX_INITIAL_WINDOWS, Analysis, Budget, initial_window_count, main

PICKED_UP = Path(__file__).resolve().parents[1] / "experiments/LeftBag_PickedUp_live.GEfpzE/run/analysis.json"


@pytest.mark.parametrize(("seconds", "windows"), [
    (25.0, 3), (34.8, 4), (40.56, 5), (54.48, 6), (65.8, 7), (10.0, 1), (10.000001, 2), (600.0, MAX_INITIAL_WINDOWS),
])
def test_window_count_covers_the_whole_video_up_to_the_cap(seconds, windows):
    assert initial_window_count(round(seconds * 1_000_000), 10_000_000) == windows


@pytest.mark.parametrize("value", ["0", "13", "three"])
def test_explicit_window_count_is_bounded(tmp_path, value):
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path / "v.mkv"), "--live", "--authorize-footage-transfer",
              "--authorize-observation-text-transfer", "--max-initial-windows", value, "--output", str(tmp_path / "o")])
    assert error.value.code == 2


def picked_up():
    analysis = TypeAdapter(Analysis).validate_python(json.loads(PICKED_UP.read_text())["analysis"])
    bag = next(f for f in analysis.observations if f.observation.category == "object_placed")
    calls = []

    def inspect(interval, modality, **options):
        calls.append((interval, options))
        raise VideoError("offline: dispatch reached")

    run = AgentRun(analysis.video, None, inspect, Budget(max_inspections=4, max_agent_calls=14), [],
                   sampled_indices={f.display_index for e in analysis.evidence if e.status == "success"
                                    for f in e.inspection.frames})
    run.can_reconsider = True
    return analysis, bag, run, calls


def test_live_after_state_request_for_the_bag_is_now_dispatched():
    analysis, bag, run, calls = picked_up()
    assert bag.citation.interval == Interval(18_039_700, 19_519_712)
    assert inspection_scope(bag, analysis.video.duration_us) == Interval(13_039_700, 24_519_712)
    # The exact request rejected live as inspection_outside_candidate (archived role decision).
    decision = {"action": "inspect", "modality": "frames", "start_us": 19_759_700, "end_us": 24_759_700,
                "sampling_step_ms": 500, "reason": "Does the person stand up and leave the black bag on the floor?"}
    assert run.reinspect(bag, decision, {bag.observation.id: bag}) == {"status": "failed"}
    (interval, options), = calls
    assert interval == Interval(19_759_700, 24_759_700) and options["sampling_step_ms"] == 500


def test_margin_is_bounded_and_limited_to_placement_and_removal():
    analysis, bag, run, calls = picked_up()
    too_late = {"action": "inspect", "modality": "frames", "start_us": 24_600_000, "end_us": 29_000_000,
                "reason": "Later."}
    with pytest.raises(InspectionRejected) as error:
        run.reinspect(bag, too_late, {bag.observation.id: bag})
    assert error.value.code == "inspection_outside_candidate" and not calls
    walker = next(f for f in analysis.observations if f.observation.category == "person_moved"
                  and f.citation.interval.end_us <= 19_600_000)
    after = {"action": "inspect", "modality": "frames", "start_us": walker.citation.interval.end_us + 300_000,
             "end_us": walker.citation.interval.end_us + 3_000_000, "reason": "After."}
    assert inspection_scope(walker, analysis.video.duration_us) == walker.citation.interval
    with pytest.raises(InspectionRejected) as error:
        run.reinspect(walker, after, {walker.observation.id: walker})
    assert error.value.code == "inspection_outside_candidate"


def test_verification_context_states_the_scope_for_actions_only():
    analysis, bag, run, _ = picked_up()
    captured = []
    run.decide = lambda role, context: captured.append(context)
    run.remaining = 10
    run.verification_action(bag, {bag.observation.id: bag}, 0, None)
    assert captured[0]["inspection_scope_us"] == {"start_us": 13_039_700, "end_us": 24_519_712}
    walker = next(f for f in analysis.observations if f.observation.category == "person_moved")
    run.verification_action(walker, {walker.observation.id: walker}, 0, None)
    assert "inspection_scope_us" not in captured[1]
