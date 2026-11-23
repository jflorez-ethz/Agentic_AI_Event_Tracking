import json

import httpx
import pytest
from google import genai

import verification


@pytest.mark.parametrize("enhanced", [False, True])
@pytest.mark.parametrize(("variant", "status"), [
    ("approach", "supported"), ("visible_divergence", "supported"),
    ("nearby", "supported"), ("unresolved", "insufficient"),
    ("invalid_frame", None), ("invalid_interval", None), ("separation", None), ("identity_links", None),
    ("abstain", None), ("unknown_id", None),
    ("valid_movement_approach", "supported"), ("valid_movement_invalid_frame", None),
    ("invalid_movement_invalid_frame", None),
])
def test_autonomous_proposal_from_targeted_media(tmp_path, monkeypatch, variant, status, enhanced):
    movement, _, claim = variant.partition("_movement_")
    if claim:
        variant = claim
    seed = json.loads((verification.HANDOFF / "decision.json").read_text())["ids"][0]
    media, decisions = [], []
    real_client = genai.Client
    selected = []

    def respond(request):
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        schema = body["generationConfig"]["responseJsonSchema"]
        if any("inlineData" in part for part in parts):
            media.append(body)
            assert len([p for p in parts if "inlineData" in p]) == 3
            assert "relation" in schema["properties"]
            assert "relational_reviews" not in json.dumps(body)
            assert "source time 6000000" in json.dumps(parts)
            claim = variant if variant in ("nearby", "unresolved", "visible_divergence", "separation") else "approach"
            marks = [
                [{"x": 20, "y": 50, "radius": 1}, {"x": 100, "y": 50, "radius": 1}],
                [{"x": 40, "y": 50, "radius": 1}, {"x": 80, "y": 50, "radius": 1}],
            ]
            if claim == "visible_divergence":
                marks.reverse()
            views = [{"frame_label": "F1", "marks": marks[0]},
                     {"frame_label": "F2" if variant != "invalid_frame" else "F99", "marks": marks[1]}]
            if claim == "unresolved":
                views[1]["marks"] = None
            nearby = claim == "nearby"
            relation = {"claim": claim, "interval": {"start_us": 6_000_000,
                         "end_us": 6_000_001 if nearby else 6_520_001 + (variant == "invalid_interval")},
                        "views": views[:1] if nearby else views,
                        "nearby_frame_label": "F1" if nearby else None, "distinct_paths": claim == "visible_divergence"}
            if variant == "identity_links":
                relation["links"] = [{"before_id": "F1", "after_id": "F2", "correspondence": [0, 1]}]
            answer = {"observations": [{
                "category": "person_moved", "description": "Two people approach each other.",
                "visibility_limits": "Distant", "uncertainty": "Local only",
                "frame_labels": ["F1", "F2"], "clip_interval_us": [],
            }], "relation": None if variant == "abstain" else relation}
        else:
            context = json.loads(parts[0]["text"])
            assert "relational_reviews" not in context
            if "candidate_id" not in context:
                answer = {"action": "report", "lead_id": None, "emphasis": "uncertainty"}
            else:
                candidate = context["candidate_id"]
                decisions.append((context, schema))
                answer = {"action": "verdict", "ids": [candidate], "verdict": "insufficient", "correspondence": []}
                if candidate == seed and context["last_tool_result"] is None:
                    assert not context["relational_proposals"]
                    answer = {"action": "inspect", "modality": "frames", "start_us": 6_000_000,
                              "end_us": 7_500_000, "relational": True}
                    if enhanced:
                        assert context["relational_selection"]
                        answer["visual_question"] = "How does the spacing between the silhouettes change?"
                        answer["reason"] = "Individual movement descriptions do not establish relative spacing."
                elif candidate == seed:
                    if context["relational_proposals"]:
                        identifier, = context["relational_proposals"]
                        selected.append(identifier)
                        answer["relation_proposal_id"] = "unknown" if variant == "unknown_id" else identifier
                    if movement in ("valid", "invalid"):
                        answer["verdict"] = "supported"
                    if movement == "valid":
                        frames = context["evidence"][seed]["frame_ids"]
                        answer["transition"] = {"observation_id": seed,
                                                "before_frame_id": frames[0], "after_frame_id": frames[-1]}
            answer.setdefault("reason", "Scripted decision.")
        return httpx.Response(200, json={"candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]}}]})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    out = tmp_path / "autonomous"
    assert verification.main([*(["--relational-selection"] if enhanced else []),
                              "--output", str(out), "--autonomous-relations",
                              "--authorize-footage-transfer", "--authorize-observation-text-transfer",
                              "--question", "What happened after the two people approached each other?"]) == 0
    result = json.loads((out / "result.json").read_text())
    assert len(media) == 1 and result["physical_requests"] == (8 if movement == "invalid" else 7)
    movement_event, = [e for e in result["events"] if e["observation_ids"][0] == seed]
    assert movement_event["verdict"] == ("supported" if movement == "valid" else "insufficient")
    if enhanced:
        inspection, = [row for row in result["trace"] if row["action"] == "inspect"]
        assert inspection["details"]["visual_question"].endswith("change?")
        assert "relative spacing" in inspection["details"]["evidence_gap"]
        assert "relative spacing" not in json.dumps(media[0])
        assert result["decisions"][0]["context"]["overlapping_observations"]
    target, = result["targeted_evidence"]
    assert target["status"] == "success"
    relations = [e["relation"] for e in result["events"] if e["relation"]]
    if status:
        relation, = relations
        assert relation["status"] == status and relation["continuity"] == "unresolved"
        assert relation["claim"] == variant
        assert relation["interval"] == target["relation"]["interval"]
        assert json.loads(target["relational_raw_response"])["relation"]["claim"] == variant
        assert relation["source"] == "targeted_perception"
        ids = [f["id"] for cite in relation["citations"] for f in cite["frames"]]
        assert ids == [f["id"] for f in target["inspection"]["frames"][:len(ids)]]
        assert selected and "Person continuity unresolved" in (out / "report.md").read_text()
    else:
        assert not relations
        assert bool(selected) == (variant == "unknown_id")
        assert bool(target["relation_error"]) == (variant not in ("abstain", "unknown_id"))
        if variant == "unknown_id":
            assert any(r["action"] == "relation_rejected" and "Unknown" in r["reason"] for r in result["trace"])
    for part in media[0]["contents"][0]["parts"]:
        if "inlineData" in part:
            part["inlineData"]["data"] = "<omitted>"
    (out / "mock-requests.json").write_text(json.dumps({"media": media[0], "verification": decisions}, indent=2))
    anchor = result["answers"][0]["anchor"]
    assert (anchor is not None) == (variant == "approach")


def test_prepared_review_and_autonomous_modes_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as error:
        verification.main(["--output", str(tmp_path / "run"), "--autonomous-relations",
                           "--relational-reviews", "review.json"])
    assert error.value.code == 2
