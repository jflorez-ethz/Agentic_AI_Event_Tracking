"""Watch-list levels in the alert queue (docs/watch-list.md, draft A1). Offline."""
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter
import json

from security_augmented import floor_check
from security_augmented.review import NEVER_DISMISSED, WATCH_LEVEL, review

ROOT = Path(__file__).resolve().parents[1]


def load(run):
    from security_augmented.workflow import Analysis

    return TypeAdapter(Analysis).validate_python(json.loads((ROOT / "experiments" / run / "analysis.json").read_text())["analysis"])


@pytest.fixture(scope="module")
def box():
    analysis = load("leftbox_live.1iXjTj/run")
    (event,) = [e for e in analysis.unresolved if e.category == "object_placed"]
    return analysis, event


def test_levels_match_the_draft():
    assert {c for c, level in WATCH_LEVEL.items() if level == 1} == {"person_on_floor", "person_fell", "object_placed"}
    assert {c for c, level in WATCH_LEVEL.items() if level == 2} == {"person_enters_area", "object_removed"}
    assert {c for c, level in WATCH_LEVEL.items() if level == 3} == {"person_moved", "person_appeared"}
    assert NEVER_DISMISSED == {"person_on_floor", "person_fell", "object_placed"}


@pytest.mark.parametrize("verdict, reason", [("unsupported", "The frames show no placement."),
                                             ("insufficient", "Observation deferred during triage.")])
def test_level_1_object_left_is_always_an_alert(box, verdict, reason):
    analysis, event = box
    (alert,) = review((replace(event, verdict=verdict, reason=reason),), analysis.trace, analysis.evidence)["alerts"]
    assert alert["level"] == 1 and alert["category"] == "object_placed"


def test_level_2_unchanged(box):
    analysis, event = box
    removed = replace(event, category="object_removed", verdict="unsupported", reason="The frames show no removal.")
    result = review((removed,), analysis.trace, analysis.evidence)
    assert not result["alerts"] and result["not_alerted"][0]["why"] == "contradicted"
    entry = replace(event, category="person_enters_area", verdict="insufficient", reason="Observation deferred during triage.")
    result = review((entry,), analysis.trace, analysis.evidence)
    assert not result["alerts"] and result["not_alerted"][0]["why"] == "zone_undefined"


@pytest.mark.parametrize("category", ["person_moved", "person_appeared"])
def test_level_3_is_never_an_alert(box, category):
    analysis, event = box
    for verdict in ("unsupported", "insufficient"):
        result = review((replace(event, category=category, verdict=verdict),), analysis.trace, analysis.evidence)
        assert not result["alerts"] and not result["not_alerted"]


def test_level_3_postures_are_described_not_alerted():
    s = 1_000_000
    for posture, status in (("kneeling", "kneeling_only"), ("sitting_on_seat", "seated_only")):
        seq = [(8 * s + i * 420_000, "standing" if i < 3 else posture, 0.5, 0.5, "probe") for i in range(15)]
        facts = floor_check.describe(seq, 9 * s, aspect=0.75, video_end_us=60 * s)
        incident = {**facts, "anchor_us": 9 * s}
        assert facts["status"] == status and floor_check.alerting([incident]) == []
        assert "Chronologie (sans alerte)" in floor_check.render_markdown([incident])


def test_level_1_person_on_the_floor_is_always_an_alert():
    for reason in ("upright_throughout", "probe_failed", "budget_exhausted", "not_corroborated"):
        incident = {"status": "to_review", "reason": reason, "anchor_us": 1}
        assert floor_check.alerting([incident]) == [incident]
