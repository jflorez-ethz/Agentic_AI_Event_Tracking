"""Plain-language guard report built from saved analysis.json files (no model calls)."""
import json
import re
import shutil
from pathlib import Path

import pytest

from security_augmented import guard_report

RUNS = Path(__file__).resolve().parents[1] / "experiments"
TECHNICAL = re.compile(r"(?:frame|observation|inspection|video|alert)-[0-9a-f]{16}|[0-9a-f]{40}")


def result(run):
    return json.loads((RUNS / run / "run/analysis.json").read_text())


def text(page):
    page = re.sub(r'data:image/jpeg;base64,[^"]+', "", page)
    return " ".join(re.sub(r"<[^>]+>", " ", page[page.index("<main>"):]).split())


def headline(page):
    return re.search(r'<p class="headline[^"]*">([^<]+)</p>', page).group(1)


def test_fall_report_structure_and_images():
    page = guard_report.render(result("fall_live.Q2OExt"))
    assert headline(page) == "Person down at 00:25"
    plain = text(page)
    order = [plain.index(h) for h in ("Coverage", "Needs operator review", "Confirmed security events",
                                      "Everything seen, in order", "Limits")]
    assert order == sorted(order)
    assert "Duration 00:40" in plain and "Analysed: the whole video" in plain and "Model processing time" in plain
    assert "lies on the floor from 00:28–00:29" in plain  # frame labels become clock times
    assert page.count('<img src="data:image/jpeg;base64,') == 3
    assert [c for c in re.findall(r"<figcaption>([^<]+)</figcaption>", page)] == [
        "Before · 00:25", "During · 00:27", "After · 00:29"]
    assert not TECHNICAL.search(re.sub(r'data:image/jpeg;base64,[^"]+', "", page))
    assert 'href="report.md"' in page


def test_old_run_gets_its_review_queue_and_alert_images():
    page = guard_report.render(result("leftbox_live.1iXjTj"))  # saved before analysis.review existed
    assert headline(page) == "1 possible security event needs review"
    plain = text(page)
    assert "Was an object put down and left there?" in plain and "Object left" in plain
    assert "it had already seen them all" in plain
    assert page.count("<img ") == 3 and "Person walking" not in headline(page)


@pytest.mark.parametrize(("run", "expected"), [
    ("leftbox_live.HwKyEx", "Object left at 00:20"),
    ("LeftBag_PickedUp_live.kocJd7", "Object left at 00:18"),
    ("Walk2_live.m2MsOp", "No security event found in the analysed part of the video"),
])
def test_headline_is_a_security_event_never_routine(run, expected):
    page = guard_report.render(result(run))
    assert headline(page) == expected
    assert "walking" not in headline(page).lower() and "came into view" not in headline(page).lower()


@pytest.mark.parametrize("run", ["TwoEnterShop1front_live.yuMI6O", "LeftBag_PickedUp_live.kocJd7",
                                 "fall_live.Q2OExt", "leftbox_live.HwKyEx"])
def test_every_perception_observation_reaches_the_guard(run):
    from pydantic import TypeAdapter
    from security_augmented.workflow import Analysis

    data = result(run)
    analysis = TypeAdapter(Analysis).validate_python(data["analysis"])
    seen = {f.observation.id for e in analysis.evidence for f in e.findings}
    rows = guard_report.timeline_rows(analysis, guard_report.review_queue(analysis))
    assert {i for r in rows for i in r["members"]} == seen  # nothing Perception saw is dropped
    page = guard_report.render(data)
    items = re.findall(r'<li class="row ([^"]+)">(.*?)</li>', page, re.S)
    assert len(items) == len(rows)
    for classes, item in items:
        # Only verified rows are stated as facts; others are attributed to the video analysis.
        assert ("Reported by the video analysis" in item) == ("verified" not in classes.split())
        assert ("security" in classes.split()) == ("Security</span>" in item)  # red is backed by a label
    summary = re.search(r'<p class="summary">([^<]+)</p>', page).group(1)
    assert len(re.findall(r"[.!?](?:\s|$)", summary)) == 2
    assert f"{len(rows)} things were seen" in summary
    assert '<svg class="coverage"' in page and "sampled moments" in page


def test_store_exit_is_shown_not_dropped():
    page = guard_report.render(result("TwoEnterShop1front_live.yuMI6O"))
    plain = text(page)
    assert "moving from inside the store into the upper-level hallway corridor" in plain  # the 00:50 exit
    assert "no zone is configured" in plain
    assert "01:03" in plain  # observations Investigation never saw still appear


def test_missing_video_still_renders_with_a_note():
    data = result("fall_live.Q2OExt")
    data["analysis"]["video"]["source_path"] = "/nonexistent/video.mpg"
    page = guard_report.render(data)
    assert page.count("image unavailable") == 3 and "the video file is not available" in page


def test_write_leaves_report_md_untouched(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(RUNS / "fall_live.Q2OExt/run", run)
    before = (run / "report.md").read_bytes()
    assert guard_report.main([str(run)]) == 0
    assert (run / "report.html").read_text().startswith("<!doctype html>")
    assert (run / "report.md").read_bytes() == before
    assert guard_report.main([]) == 2
