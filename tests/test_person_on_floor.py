"""person_on_floor end to end: Perception reports, the code checks the facts, the guard gets an alert. Offline.

Replaces the person_fell contract (a model-judged before/after pair): Verification never receives a person on the
floor, and 'supported' only comes from the code-side check (floor_check.py).
"""
import json

import pytest

from security_augmented import floor_check
from security_augmented.contracts import VideoError
from security_augmented.observation import FrameReference, InferenceMetadata, Observation, ObservationResult, PostureResult
from security_augmented.video import _run
from security_augmented.workflow import EVENT_LABELS, LEGACY_LABELS, Budget, InspectionPlan, _event_label, analyze_video

META = InferenceMetadata("offline", "mock", None, "1", "1")


def make_video(path):
    """A tall 'upright' figure for 0-3 s, then a wide figure low in the image for 3-8 s (5 fps)."""
    _run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=96x64:r=5:d=8",
         "-vf", "drawbox=x=40:y=10:w=10:h=44:color=white:t=fill:enable='lt(t,3)',"
                "drawbox=x=25:y=48:w=44:h=10:color=white:t=fill:enable='gte(t,3)'",
         "-c:v", "ffv1", str(path))


class Provider:
    """Initial scan reports person_on_floor at 3 s; the posture probe answers with `posture_at(t_s)`."""

    def __init__(self, posture_at, *, category="person_on_floor", fail=False):
        self.posture_at, self.category, self.fail = posture_at, category, fail
        self.posture_requests = []

    def infer(self, request):
        assert "person_on_floor" in request.categories and "person_fell" not in request.categories
        inspection = request.media.inspection
        if inspection.requested_interval.start_us != 0:
            return ObservationResult(META, ())
        cited = [f for f in inspection.frames if f.source_time_us >= 3_000_000][:2]
        observation = Observation("floor", inspection.id, self.category,
                                  "A person in white lies on the floor near the bottom of the image.",
                                  FrameReference(tuple(f.id for f in cited)), "Fixed view.", "Posture only.")
        return ObservationResult(META, (observation,))

    def postures(self, request):
        self.posture_requests.append(request)
        if self.fail:
            raise VideoError("probe unavailable")
        frames = tuple({"frame_id": f.id, "persons": ({"id": "P1", "posture": self.posture_at(f.source_time_us / 1e6),
                                                       "x": 0.5, "y": 0.8},)} for f in request.media.inspection.frames)
        return PostureResult(META, frames)


def run(provider):
    calls = []

    def decide(role, context):
        calls.append((role, json.dumps(context)))
        if role == "investigation":
            return {"action": "delegate", "ids": list(context["evidence"]), "dispositions": [], "reason": "Check."}
        if role == "reporting":
            return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
        raise AssertionError("Verification must never receive a person on the floor")

    return analyze_video(VIDEO, provider, decide=decide, controller="langgraph",
                         plan=InspectionPlan(window_us=4_000_000, frame_step_us=1_000_000),
                         budget=Budget(max_initial_windows=2, max_inspections=0, max_agent_calls=6)), calls


@pytest.fixture(scope="module", autouse=True)
def video(tmp_path_factory):
    pytest.importorskip("langgraph")
    global VIDEO
    VIDEO = tmp_path_factory.mktemp("floor") / "floor.mkv"
    make_video(VIDEO)


def test_person_on_floor_facts_reach_timeline_report_queue_and_questions():
    provider = Provider(lambda t: "standing" if t < 3 else "lying_on_floor")
    result, calls = run(provider)
    assert not any(role == "verification" for role, _ in calls)
    assert all("floor" not in context for role, context in calls if role == "investigation")
    (event,) = [e for e in result.timeline if e.category == "person_on_floor"]
    assert event.verdict == "supported" and event.interval.start_us == 3_000_000
    (incident,) = result.floor_incidents
    assert incident["status"] == "verified" and incident["arrival"]["observed"]
    assert incident["outcome"]["kind"] == "on_floor_at_end"
    # Neutral probe: no description, no event word; dedicated prompt version; counted as media evidence.
    (request,) = provider.posture_requests
    assert "lies on the floor near the bottom" not in request.prompt and "fall" not in request.prompt.lower()
    assert tuple(request.vocabulary) == tuple(floor_check.RULES["vocabulary"])
    assert any(e.phase == "floor_probe" for e in result.evidence)
    report = result.report
    assert report.startswith("## Personnes au sol (1)") and "faits vérifiés" in report
    assert "De debout" in report and "allongée au sol" in report and "Toujours au sol à la fin de la vidéo" in report
    assert "chute" not in report.lower()
    (alert,) = result.review["floor_alerts"]
    assert alert["status"] == "facts_verified" and alert["frames"]
    assert result.review["counts"]["floor"] == 1
    assert result.ask("Is someone lying on the floor?").events == (event,)


def test_false_report_stays_an_alert_to_review_and_is_never_confirmed():
    """System-level regression of the held-out Slump case: Perception says on the floor, the probe sees standing."""
    result, calls = run(Provider(lambda t: "standing"))
    assert not any(role == "verification" for role, _ in calls)
    assert not [e for e in result.timeline if e.category == "person_on_floor"]
    (event,) = [e for e in result.unresolved if e.category == "person_on_floor"]
    assert event.verdict == "insufficient"
    (alert,) = result.review["floor_alerts"]
    assert (alert["status"], alert["reason_code"]) == ("needs_review", "upright_throughout")
    assert "à vérifier" in result.report and "debout tout du long" in result.report


def test_probe_failure_is_recorded_and_left_to_review():
    result, _ = run(Provider(lambda t: "standing", fail=True))
    (incident,) = result.floor_incidents
    assert (incident["status"], incident["reason"]) == ("to_review", "probe_failed")
    assert any(e.phase == "floor_probe" and e.status == "failed" for e in result.evidence)
    assert result.review["floor_alerts"][0]["status"] == "needs_review"


def test_kneeling_only_gives_no_alert():
    result, _ = run(Provider(lambda t: "standing" if t < 3 else "kneeling"))
    (incident,) = result.floor_incidents
    assert incident["status"] == "kneeling_only"
    assert result.review["floor_alerts"] == [] and "Chronologie (sans alerte)" in result.report


def test_archived_person_fell_stays_readable():
    assert "person_fell" not in EVENT_LABELS and "person_fell" in LEGACY_LABELS

    class Legacy:
        category = "person_fell"
        relation = None
    assert _event_label(Legacy()) == LEGACY_LABELS["person_fell"]


def test_gemini_posture_probe_schema_and_validation():
    from security_augmented.gemini import GeminiAdapter, POSTURE_PROMPT_VERSION
    from security_augmented.observation import FrameSequenceInput, PostureRequest
    from security_augmented.contracts import Interval
    from security_augmented.video import _decode, ingest, sample

    source = ingest(VIDEO)
    inspection = sample(source, Interval(0, 2_000_001), [1_000_000, 2_000_000])
    media = FrameSequenceInput(inspection, source.width, source.height,
                               _decode(source, tuple(f.display_index for f in inspection.frames)))
    request = PostureRequest(media, tuple(floor_check.RULES["vocabulary"]), floor_check.prompt())
    sent = []

    class Response:
        def __init__(self, text):
            self.text, self.candidates, self.usage_metadata, self.model_version = text, [type("C", (), {"finish_reason": "STOP"})()], None, "m"

    def client(answer):
        class Models:
            def generate_content(self, **kwargs):
                sent.append(kwargs)
                return Response(json.dumps(answer))
        return type("Client", (), {"models": Models()})()

    good = {"frames": [{"frame_label": "F1", "persons": [{"id": "P1", "posture": "standing", "x": 0.4, "y": 0.5}]},
                       {"frame_label": "F2", "persons": []}]}
    result = GeminiAdapter(client=client(good), sdk_version="test").postures(request)
    assert result.metadata.prompt_version == POSTURE_PROMPT_VERSION
    assert [len(f["persons"]) for f in result.frames] == [1, 0]
    schema = json.dumps(sent[0]["config"]["response_json_schema"])
    assert "sitting_on_floor" in schema and "person_fell" not in schema and "fall" not in sent[0]["contents"][0]["parts"][0]["text"].lower()
    bad = {"frames": [{"frame_label": "F1", "persons": [{"id": "P1", "posture": "fallen", "x": 0.4, "y": 0.5}]},
                      {"frame_label": "F2", "persons": []}]}
    with pytest.raises(VideoError, match="posture"):
        GeminiAdapter(client=client(bad), sdk_version="test").postures(request)


def test_guard_report_shows_facts_strip_and_images():
    from dataclasses import asdict

    from security_augmented import guard_report

    result, _ = run(Provider(lambda t: "standing" if t < 3 else "lying_on_floor"))
    page = guard_report.render(json.loads(json.dumps({"analysis": asdict(result)})))
    assert "Person on the floor at 00:03 (facts verified)" in page
    assert "<h2>People on the floor</h2>" in page and 'class="posture"' in page and "p-floor" in page
    assert "From standing" in page and "Still on the floor at the end of the video" in page
    assert page.count("data:image/jpeg;base64,") >= 2
    assert "fall" not in page.lower().replace("fallback", "")
    # A person on the floor is not repeated among generic confirmed events.
    confirmed = page.split("<h2>Confirmed security events</h2>")[1].split("<h2>")[0]
    assert "Person on the floor" not in confirmed


def test_question_routing_for_the_floor():
    from security_augmented.workflow import _query_categories

    assert "person_on_floor" in _query_categories("is someone lying on the floor?")
    assert "person_on_floor" in _query_categories("did anyone fall?")
    assert "person_on_floor" not in _query_categories("what was put down?")
