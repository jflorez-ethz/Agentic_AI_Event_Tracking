"""Perception's possible_category on unclear observations, and its route to the operator review queue."""
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from security_augmented import guard_report
from security_augmented.contracts import Interval, VideoError
from security_augmented.gemini import GeminiAdapter, _response_schema
from security_augmented.observation import FrameSequenceInput, InferenceMetadata, ObservationRequest
from security_augmented.review import review
from security_augmented.video import _decode, ingest, sample
from security_augmented.workflow import EVENT_LABELS, PERCEPTION_CATEGORIES, Analysis, InspectionPlan, _observe_video
from test_new_video import make_video

RUNS = Path(__file__).resolve().parents[1] / "experiments"


@pytest.fixture
def frames_request(tmp_path):
    path = tmp_path / "block.mkv"
    make_video(path)
    video = ingest(path)
    inspection = sample(video, Interval(0, 4_000_000), [0, 1_000_000, 2_000_000, 3_000_000])
    pixels = _decode(video, tuple(f.display_index for f in inspection.frames))
    media = FrameSequenceInput(inspection, video.width, video.height, pixels)

    def build(flag):
        return ObservationRequest(media, PERCEPTION_CATEGORIES, "Describe.", possible_category=flag)
    return video, build


def test_schema_and_instruction_only_when_asked(frames_request):
    _, build = frames_request
    schema = _response_schema(PERCEPTION_CATEGORIES, possible_category=True)
    field = schema["properties"]["observations"]["items"]["properties"]["possible_category"]
    assert field["enum"] == [*EVENT_LABELS, "none"]
    assert "possible_category" in schema["properties"]["observations"]["items"]["required"]
    adapter = GeminiAdapter(model="m", single_request=True)
    asked, plain = adapter.prepare(build(True)), adapter.prepare(build(False))
    assert "Set possible_category on every observation" in asked.contents[0]["parts"][0]["text"]
    assert "possible_category" not in json.dumps(plain.config) + json.dumps(plain.contents[0]["parts"][0])
    assert plain.config == {**plain.config, "response_json_schema": _response_schema(PERCEPTION_CATEGORIES)}


def parse(request, items):
    meta = InferenceMetadata("offline", "mock", None, "1", "1")
    return GeminiAdapter._parse(request, json.dumps({"observations": items}), meta, None).observations


def item(category, suspected=None, label="F2"):
    row = {"category": category, "description": "A person bends next to a dark item.", "visibility_limits": "Far.",
           "uncertainty": "Placed or picked up?", "frame_labels": [label], "clip_interval_us": []}
    if suspected is not None:
        row["possible_category"] = suspected
    return row


def test_parsing_keeps_the_suspicion_only_on_unclear_observations(frames_request):
    _, build = frames_request
    unclear, walking, missing = parse(build(True), [item("insufficient_evidence", "object_removed"),
                                                     item("person_moved", "object_removed"),
                                                     item("insufficient_evidence")])
    assert unclear.possible_category == "object_removed"
    assert walking.possible_category is None and missing.possible_category is None
    with pytest.raises(VideoError):
        parse(build(True), [item("insufficient_evidence", "fire")])
    with pytest.raises(VideoError):
        parse(build(False), [item("insufficient_evidence", "object_removed")])  # not asked, not accepted


def test_flag_reaches_the_request_only_for_model_guided_perception(frames_request):
    video, _ = frames_request
    seen = []

    class Provider:
        def infer(self, request):
            seen.append(request.possible_category)
            raise VideoError("stop")
    for guided in (True, False):
        _observe_video(video, Provider(), Interval(0, 4_000_000), "frames", "initial", InspectionPlan(4_000_000, 1_000_000),
                       model_guided=guided, possible_category=True)
    assert seen == [True, False]


# The eight archived unclear observations, with the category a reader would expect Perception to suspect.
SIMULATED = {
    ("LeftBag_AtChair_live.JKYE8j/run", 35.04): "object_removed",    # XML pickup 37.20 s
    ("LeftBag_PickedUp_live.GEfpzE/run", 17.52): "object_placed",    # already an alert in that run
    ("e1_offline_investigation_001", 37.44): "object_placed",        # placement already supported
    ("fall_live.spFaYl/run", 11.52): "person_fell",                  # no fall then (XML fall 26.44 s)
    ("fall_live.spFaYl/run", 26.04): "person_fell",                  # fall already supported
    ("meet_walk_pts_20261122_013252", 13.0): None,
    ("meet_walk_split_500ms.bqVoWC/run", 20.0): None,
    ("mvp_live.6R7h4T/run", 6.0): None,
}


def with_suspicions(run, seconds):
    analysis = TypeAdapter(Analysis).validate_python(json.loads((RUNS / run / "analysis.json").read_text())["analysis"])
    picks = {key[1]: value for key, value in SIMULATED.items() if key[0] == run}

    def tag(finding):
        o = finding.observation
        start = round(finding.citation.interval.start_us / 1e6, 2)
        if o.category == "insufficient_evidence" and start in picks:
            return replace(finding, observation=replace(o, possible_category=picks[start]))
        return finding
    return replace(analysis, evidence=tuple(replace(e, findings=tuple(tag(f) for f in e.findings)) for e in analysis.evidence))


@pytest.mark.parametrize(("run", "expected"), [
    ("LeftBag_AtChair_live.JKYE8j/run", [("object_removed", 35.04)]),
    ("LeftBag_PickedUp_live.GEfpzE/run", []),
    ("e1_offline_investigation_001", []),
    ("fall_live.spFaYl/run", [("person_fell", 11.52)]),
    ("meet_walk_pts_20261122_013252", []),
    ("meet_walk_split_500ms.bqVoWC/run", []),
    ("mvp_live.6R7h4T/run", []),
])
def test_simulated_routing_matches_the_step_table(run, expected):
    analysis = with_suspicions(run, None)
    queue = review((*analysis.timeline, *analysis.unresolved), analysis.trace, analysis.evidence)
    unclear = [(a["category"], round(a["interval"]["start_us"] / 1e6, 2)) for a in queue["alerts"] if a.get("unclear")]
    assert unclear == expected
    assert queue["counts"]["unclear"] == len(expected)


def test_guard_report_shows_a_possible_event():
    analysis = with_suspicions("LeftBag_AtChair_live.JKYE8j/run", None)
    data = json.loads((RUNS / "LeftBag_AtChair_live.JKYE8j/run/analysis.json").read_text())
    from dataclasses import asdict
    data["analysis"] = json.loads(json.dumps(asdict(replace(analysis, review=None)), default=str))
    page = guard_report.render(data)
    assert "1 possible security event needs review" in page
    assert "Possible: Object taken" in page and "Was an object taken away?" in page
    assert "possibly: object taken" in page
