"""person_on_floor end to end: Perception reports, the code checks the facts, the guard gets an alert. Offline.

Replaces the person_fell contract (a model-judged before/after pair): Verification never receives a person on the
floor, and a person on the floor is never 'supported': the code measures facts and doubt signals, the guard judges.
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

    def __init__(self, posture_at, *, category="person_on_floor", fail=False, box=None, assessment=None):
        self.posture_at, self.category, self.fail, self.box, self.assessment = posture_at, category, fail, box or {}, assessment
        self.posture_requests, self.assessment_prompts = [], []

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
                                                       "x": 0.5, "y": 0.8, **self.box},)} for f in request.media.inspection.frames)
        return PostureResult(META, frames)

    def floor_assessment(self, prompt):
        self.assessment_prompts.append(prompt)
        if self.assessment is None:
            raise VideoError("assessment unavailable")
        return self.assessment, {"prompt_version": "floor-assess-v1", "usage": {"prompt_token_count": 120}}


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


def test_person_on_floor_facts_reach_report_queue_and_questions_never_as_supported():
    provider = Provider(lambda t: "standing" if t < 3 else "lying_on_floor",
                        assessment="The postures are consistent with a fall or with lying down to rest.")
    result, calls = run(provider)
    assert not any(role == "verification" for role, _ in calls)
    assert all("floor" not in context for role, context in calls if role == "investigation")
    assert not [e for e in result.timeline if e.category == "person_on_floor"]  # never "supported"
    (event,) = [e for e in result.unresolved if e.category == "person_on_floor"]
    assert event.verdict == "insufficient" and event.interval.start_us == 3_000_000
    (incident,) = result.floor_incidents
    assert incident["seen"] == "on_floor" and incident["arrival"]["observed"] and incident["first_look"] == "reported"
    assert incident["outcome"]["kind"] == "on_floor_at_end"
    assert incident["status"] == "no_doubt_signal" and incident["doubt_signals"] == []
    # Neutral probe: no description, no event word; dedicated prompt version; counted as media evidence.
    (request,) = provider.posture_requests
    assert "lies on the floor near the bottom" not in request.prompt and "fall" not in request.prompt.lower()
    assert tuple(request.vocabulary) == tuple(floor_check.RULES["vocabulary"])
    assert any(e.phase == "floor_probe" for e in result.evidence)
    # The assessment sees timed postures and facts only: never the first look's description, never the signals.
    (prompt,) = provider.assessment_prompts
    assert "lying on the floor from 00:03" in prompt and "lies on the floor near the bottom" not in prompt
    assert "doubt" not in prompt.lower() and "look closely" not in prompt.lower()
    assert incident["assessment"]["status"] == "ok"
    report = result.report
    assert report.startswith("## Personnes au sol, pour le garde (1)") and "aucun signal de doute mesuré" in report
    assert "Avis du système (non vérifié, en anglais) : The postures are consistent with a fall" in report
    assert "De debout" in report and "allongée au sol" in report and "Toujours au sol à la fin de la vidéo" in report
    assert "faits vérifiés" not in report
    (alert,) = result.review["floor_alerts"]
    assert alert["status"] == "no_doubt_signal" and alert["frames"] and alert["level"] == 1
    assert alert["system_assessment"].startswith("The postures are consistent with")
    assert result.review["counts"]["floor"] == 1
    answer = result.ask("Is someone lying on the floor?")
    assert answer.events == (event,) and "for the guard to judge" in answer.text and "No doubt signal" in answer.text


def test_assessment_that_states_a_fall_or_an_interpretation_is_not_shown():
    for sentence, why in (("The person fell.", "fall_stated_as_fact"), ("She is lying on the floor.", "forbidden_word"),
                          ("Lies down. Then rests.", "more_than_one_sentence"), ("The person may be injured.", "forbidden_word")):
        result, _ = run(Provider(lambda t: "standing" if t < 3 else "lying_on_floor", assessment=sentence))
        (incident,) = result.floor_incidents
        assert (incident["assessment"]["status"], incident["assessment"]["why"]) == ("rejected", why)
        assert sentence not in result.report and "Avis du système : aucun." in result.report
        assert incident["status"] == "no_doubt_signal"  # the assessment never changes the status


def test_failed_assessment_changes_nothing():
    result, _ = run(Provider(lambda t: "standing" if t < 3 else "lying_on_floor"))
    (incident,) = result.floor_incidents
    assert incident["assessment"]["status"] == "failed" and incident["status"] == "no_doubt_signal"


def test_small_person_from_the_probe_box_and_a_seat_are_look_closely():
    result, _ = run(Provider(lambda t: "standing" if t < 3 else "lying_on_floor",
                             box={"w": 0.1, "h": 0.3, "seat_nearby": True}))  # 0.3 x 64 px = 19 px tall, centre y 0.8
    (incident,) = result.floor_incidents
    assert [x["code"] for x in incident["doubt_signals"]] == ["small_person", "image_edge", "seat_nearby"]
    assert [x["value"] for x in incident["doubt_signals"][:2]] == [19, 3]  # 64 x (1 - 0.8 - 0.15) = 3 px from the border
    assert incident["status"] == "look_closely" and incident["sequence"][-1]["seat_nearby"] is True


def test_false_report_is_look_closely_and_never_confirmed():
    """System-level regression of the held-out Slump case: Perception says on the floor, the probe sees standing."""
    result, calls = run(Provider(lambda t: "standing"))
    assert not any(role == "verification" for role, _ in calls)
    assert not [e for e in result.timeline if e.category == "person_on_floor"]
    (event,) = [e for e in result.unresolved if e.category == "person_on_floor"]
    assert event.verdict == "insufficient"
    (alert,) = result.review["floor_alerts"]
    assert (alert["status"], alert["reason_code"]) == ("look_closely", "disagreement,no_floor_seen")
    assert "à regarder de près" in result.report and "debout tout du long" in result.report


def test_probe_failure_is_recorded_and_look_closely():
    result, _ = run(Provider(lambda t: "standing", fail=True))
    (incident,) = result.floor_incidents
    assert (incident["seen"], incident["status"]) == ("probe_failed", "look_closely")
    assert [x["code"] for x in incident["doubt_signals"]] == ["no_close_check"]
    assert any(e.phase == "floor_probe" and e.status == "failed" for e in result.evidence)
    assert incident["assessment"]["status"] == "not_requested"


def test_kneeling_after_an_on_the_floor_report_goes_to_the_guard():
    result, _ = run(Provider(lambda t: "standing" if t < 3 else "kneeling"))
    (incident,) = result.floor_incidents
    assert (incident["seen"], incident["status"]) == ("kneeling", "look_closely")
    (alert,) = result.review["floor_alerts"]
    assert alert["status"] == "look_closely" and "à genoux" in result.report


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

    good = {"frames": [{"frame_label": "F1", "persons": [{"id": "P1", "posture": "standing", "x": 0.4, "y": 0.5,
                                                          "w": 0.1, "h": 0.3, "seat_nearby": False}]},
                       {"frame_label": "F2", "persons": []}]}
    result = GeminiAdapter(client=client(good), sdk_version="test").postures(request)
    assert result.metadata.prompt_version == POSTURE_PROMPT_VERSION
    assert [len(f["persons"]) for f in result.frames] == [1, 0]
    schema = json.dumps(sent[0]["config"]["response_json_schema"])
    assert "sitting_on_floor" in schema and "person_fell" not in schema and "fall" not in sent[0]["contents"][0]["parts"][0]["text"].lower()
    assert '"seat_nearby": {"type": "boolean"}' in schema and POSTURE_PROMPT_VERSION == "floor-v2"
    oversized = {"frames": [{"frame_label": "F1", "persons": [{"id": "P1", "posture": "standing", "x": 0.4, "y": 0.5,
                                                               "w": 1.5, "h": 0.3, "seat_nearby": False}]},
                            {"frame_label": "F2", "persons": []}]}
    with pytest.raises(VideoError, match="box size"):
        GeminiAdapter(client=client(oversized), sdk_version="test").postures(request)
    sent.clear()
    text, metadata = GeminiAdapter(client=client({"assessment": "Consistent with sitting down."}), sdk_version="test") \
        .floor_assessment("Postures of the person checked: ...")
    assert text == "Consistent with sitting down." and metadata["prompt_version"] == "floor-assess-v1"
    assert sent[0]["contents"][0]["parts"] == [{"text": "Postures of the person checked: ..."}]  # text only, no image
    assert sent[0]["config"]["thinking_config"]["thinking_level"] == "LOW"
    bad = {"frames": [{"frame_label": "F1", "persons": [{"id": "P1", "posture": "fallen", "x": 0.4, "y": 0.5}]},
                      {"frame_label": "F2", "persons": []}]}
    with pytest.raises(VideoError, match="posture"):
        GeminiAdapter(client=client(bad), sdk_version="test").postures(request)


def test_guard_report_shows_facts_assessment_signals_strip_and_images():
    import re
    from dataclasses import asdict

    from security_augmented import guard_report

    result, _ = run(Provider(lambda t: "standing" if t < 3 else "lying_on_floor",
                             assessment="The postures are consistent with lying down on the floor."))
    page = guard_report.render(json.loads(json.dumps({"analysis": asdict(result)})))
    assert "Person on the floor at 00:03 — for the guard" in page
    floor = page.split("<h2>People on the floor — for the guard</h2>")[1].split("<h2>")[0]
    order = [floor.index(h) for h in ("<h4>Measured facts</h4>", "<h4>System's assessment</h4>", "<h4>Doubt signals</h4>",
                                      'class="posture"', "data:image/jpeg;base64,")]
    assert order == sorted(order)
    assert "<i>The postures are consistent with lying down on the floor.</i>" in floor and "not verified" in floor
    assert "No doubt signal measured. This does not mean it is true." in floor and "Look closely</span>" not in floor
    assert "From standing" in floor and "Still on the floor at the end of the video" in floor
    captions = re.findall(r"<figcaption>([^<]+)</figcaption>", floor)
    assert captions[0].startswith("Before (standing)") and captions[1].startswith("During (lying on the floor)")
    assert not any(c.startswith("After") for c in captions)  # still on the floor at the end: no "after" image
    assert page.split("<h2>Watch-list events — facts verified</h2>")[1].split("<h2>")[0].strip() == '<p class="empty">None.</p>'
    assert "facts verified)" not in page
    # Listed once, in its own section, never repeated as a generic alert.
    assert page.split("<h2>Needs guard review</h2>")[1].split("<h2>")[0].count("Person on the floor") == 0


def test_question_routing_for_the_floor():
    from security_augmented.workflow import _query_categories

    assert "person_on_floor" in _query_categories("is someone lying on the floor?")
    assert "person_on_floor" in _query_categories("did anyone fall?")
    assert "person_on_floor" not in _query_categories("what was put down?")
