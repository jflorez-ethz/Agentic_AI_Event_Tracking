"""report.html consistency for person-on-the-floor alerts (demo Slump findings, 2026-11-25). Offline."""
import json
import re
from dataclasses import asdict

import pytest

from security_augmented import floor_check, guard_report
from security_augmented.observation import FrameReference, InferenceMetadata, Observation, ObservationResult, PostureResult
from security_augmented.video import _run
from security_augmented.workflow import Budget, InspectionPlan, analyze_video

META = InferenceMetadata("offline", "mock", None, "1", "1")
S = 1_000_000
CLAIMS = {0: [1.0], 4 * S: [6.0, 7.0], 8 * S: [9.0]}  # window start -> cited times of person_on_floor reports


def posture_at(t):
    if 0.8 <= t <= 1.2:
        return "sitting_on_seat"  # the 00:01 report: a person on a seat, nobody on the floor
    return "standing" if t < 6 else "lying_on_floor"


class Provider:
    def infer(self, request):
        inspection = request.media.inspection
        times = CLAIMS.get(inspection.requested_interval.start_us, [])
        cited = [f for f in inspection.frames if any(abs(f.source_time_us / S - t) < 0.01 for t in times)]
        if not cited:
            return ObservationResult(META, ())
        return ObservationResult(META, (Observation(f"floor-{inspection.requested_interval.start_us}", inspection.id,
                                                    "person_on_floor", "A person is on the floor.",
                                                    FrameReference(tuple(f.id for f in cited)), "Fixed view.", "Posture only."),))

    def postures(self, request):
        return PostureResult(META, tuple({"frame_id": f.id, "persons": ({"id": "P1", "posture": posture_at(f.source_time_us / S),
                                                                          "x": 0.5, "y": 0.8},)} for f in request.media.inspection.frames))


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    pytest.importorskip("langgraph")
    video = tmp_path_factory.mktemp("consistency") / "v.mkv"
    _run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=96x64:r=5:d=12", "-c:v", "ffv1", str(video))

    def decide(role, context):
        if role == "investigation":
            return {"action": "delegate", "ids": list(context["evidence"]), "dispositions": [], "reason": "Check."}
        return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}

    result = analyze_video(video, Provider(), decide=decide, controller="langgraph",
                           plan=InspectionPlan(window_us=4 * S, frame_step_us=S),
                           budget=Budget(max_initial_windows=3, max_inspections=0, max_agent_calls=6))
    return result, guard_report.render(json.loads(json.dumps({"analysis": asdict(result)})))


def section(page, name):
    return page.split(f"<h2>{name}</h2>")[1].split("<h2>")[0]


def test_1_every_floor_alert_is_counted_and_visible_in_one_of_the_two_sections(page):
    result, html = page
    verified = section(html, "Watch-list events — facts verified")
    review = section(html, "Needs guard review")
    assert "None." not in verified and verified.count("Person on the floor · facts verified") == 1
    assert review.count("Person on the floor · needs guard review") == 1
    assert len(result.floor_incidents) == 2 and "People on the floor" not in html


def test_2_unverified_floor_report_goes_to_the_guard_with_what_the_check_saw(page):
    result, html = page
    (seat,) = [i for i in result.floor_incidents if i["status"] != "verified"]
    assert (seat["status"], seat["reason"]) == ("to_review", "seated")
    review = section(html, "Needs guard review")
    assert "the close check shows a person sitting on a seat, nobody on the floor" in review
    assert "What the close check saw: standing" in review and "sitting on a seat 00:00.80" in review


def test_2b_a_report_near_a_seat_check_is_still_checked_not_merged():
    s = floor_check.check([("seat", 1 * S), ("floor", 3 * S)],
                          lambda times, phase: ("i", [{"t_us": t, "display_index": n, "frame_id": str(t), "persons": [
                              {"id": "P1", "posture": "sitting_on_seat" if t < 2 * S else "standing" if t < 3 * S else "lying_on_floor",
                               "x": 0.5, "y": 0.5}]} for n, t in enumerate(times)]),
                          duration_us=20 * S, aspect=0.75)
    assert [i["observation_ids"] for i in s] == [["seat"], ["floor"]]


def test_3_verified_has_one_meaning_and_the_summary_counts_watch_list_events_only(page):
    _, html = page
    assert guard_report._SHOWN[False]["verified"] == "checked" and guard_report._SHOWN[True]["verified"] == "facts verified"
    for classes, status in re.findall(r'<li class="row ([^"]+)">.*?<span class="status">([^<]+)</span>', html, re.S):
        if "routine" in classes.split():
            assert status in ("checked", "not checked", "needs guard review", "ruled out")
        else:
            assert status in ("facts verified", "needs guard review", "not verified", "ruled out")
    assert "things were seen" not in html


def test_4_reports_of_one_incident_are_one_chronology_row(page):
    _, html = page
    rows = re.findall(r'<span class="when">([^<]+)</span><span class="what">.*?<b>Person on the floor</b>(.*?)</li>', html, re.S)
    assert len(rows) == 2
    (merged,) = [r for r in rows if "reports merged" in r[1]]
    assert merged[0].startswith("00:06") and "one incident from 00:06, 2 reports merged" in merged[1]


def test_5_summary_says_what_the_guard_has_to_do(page):
    _, html = page
    summary = re.search(r'<p class="summary">([^<]+)</p>', html).group(1)
    assert summary == ("The whole video (00:12) was analysed. "
                       "1 person on the floor (facts verified), 1 unclear case for the guard to review.")
