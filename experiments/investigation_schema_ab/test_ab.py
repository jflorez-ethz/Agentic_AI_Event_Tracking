import json

import httpx
import pytest

import ab


def test_reconstructed_context_matches_the_failed_run():
    analysis, archived = ab.load()
    context = ab.production_context(analysis)
    assert archived["http_status"] == 400 and len(context["evidence"]) == 16
    assert ab.schema_size(context) == 8939
    short, alias = ab.aliased(context)
    assert set(short["evidence"]) == {f"O{n}" for n in range(1, 17)} and ab.schema_size(short) < 2000
    assert ab.unalias({"ids": ["O1", "O16"]}, alias) == {"ids": [list(alias)[0], list(alias)[15]]}


def test_two_arms_text_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "offline")
    bodies = []

    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert not any("inlineData" in p or "inline_data" in p for c in body["contents"] for p in c["parts"])
        context = json.loads(body["contents"][0]["parts"][0]["text"])
        if any(key.startswith("observation-") for key in context["evidence"]):
            return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                                       "message": "Schema has too many states for serving."}})
        entry = next(k for k, v in context["evidence"].items() if v["category"] == "person_enters_area")
        return httpx.Response(200, json={"modelVersion": ab.MODEL, "usageMetadata": {"promptTokenCount": 1},
                                         "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
                                             "action": "delegate", "ids": [entry], "reason": "Security first.",
                                             "dispositions": [{"id": k, "status": "deferred", "reason": "Budget."}
                                                              for k in context["evidence"] if k != entry]})}]}}]})

    with pytest.raises(SystemExit):
        ab.main(["--output", str(tmp_path / "x")], transport=httpx.MockTransport(respond))
    assert not bodies
    out = tmp_path / "run"
    assert ab.main(["--authorize-observation-text-transfer", "--output", str(out)],
                   transport=httpx.MockTransport(respond)) == 0
    arms = json.loads((out / "result.json").read_text())["arms"]
    a, b = arms["a_original_ids"], arms["b_short_aliases"]
    assert a["call"]["http_status"] == 400 and a["call"]["provider_message"] == "Schema has too many states for serving."
    assert a["physical_requests"] == 1 and "decision" not in a["call"]
    assert b["decision_action"] == "delegate" and b["validation"]["status"] == "accepted"
    assert b["validation"]["delegated_categories"] == ["person_enters_area"]
    assert a["media_requests"] == b["media_requests"] == 0 and len(bodies) == 2
