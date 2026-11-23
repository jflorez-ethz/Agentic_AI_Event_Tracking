import json

import httpx
from google import genai
import pytest

from security_augmented.agent_probe import main
from security_augmented.agents import _schema


def test_probe_requires_authorization(monkeypatch):
    def unexpected(**kwargs):
        pytest.fail("Unauthorized client construction")

    monkeypatch.setattr(genai, "Client", unexpected)
    with pytest.raises(SystemExit):
        main(["--model", "gemini-3.6-flash"])


@pytest.mark.parametrize("invalid", [False, True])
def test_probe_uses_real_role_schemas(monkeypatch, capsys, invalid):
    roles = ["investigation", "verification"]
    responses = [
        {"action": "delegate", "reason": "Synthetic example.", "ids": ["synthetic-1"], "dispositions": []},
        {"action": "verdict", "reason": "Synthetic example.", "verdict": "insufficient",
         "correspondence": [], "ids": ["synthetic-1"] if not invalid else [123]},
    ]
    real_client = genai.Client

    def respond(request):
        index = 2 - len(responses)
        body = json.loads(request.content)
        assert request.url.path == "/v1beta/models/gemini-3.6-flash:generateContent"
        assert body["generationConfig"]["responseJsonSchema"] == _schema(
            roles[index], max_candidates=1 if index == 0 else None,
            observation_ids=("synthetic-1",) if index == 0 else None,
        )
        parts = body["contents"][0]["parts"]
        assert set(parts[0]) == {"text"}
        assert "synthetic-1" in parts[0]["text"]
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": json.dumps(responses.pop(0))}],
            }}],
            "usageMetadata": {"totalTokenCount": 20},
        })

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "local-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    assert main(["--authorize-synthetic-probe", "--model", "gemini-3.6-flash"]) == int(invalid)
    results = json.loads(capsys.readouterr().out)
    assert [r["schema_valid"] for r in results["role_calls"]] == [True, not invalid]
    assert results["physical_http_attempts"] == 2
    assert all(row["usage"]["total_token_count"] == 20 for row in results["role_calls"])


def test_catalog_lists_only_generation_models_across_pages(monkeypatch, capsys):
    real_client = genai.Client
    tokens = []

    def respond(request):
        assert request.method == "GET"
        assert request.url.path == "/v1beta/models"
        assert not request.content
        token = request.url.params.get("pageToken")
        tokens.append(token)
        if token is None:
            return httpx.Response(200, json={
                "models": [{"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}],
                "nextPageToken": "page-two",
            })
        return httpx.Response(200, json={
            "models": [{"name": "models/fixture", "version": "001",
                        "supportedGenerationMethods": ["generateContent"]}],
        })

    def client(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(respond)}
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "local-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    assert main(["--authorize-synthetic-probe", "--list-models"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert tokens == [None, "page-two"]
    assert result["status"] == "complete"
    assert result["models"] == [{"name": "models/fixture", "version": "001"}]


def test_verification_schema_only_offers_transition_field_for_visibility_candidates():
    from jsonschema import Draft202012Validator

    action = {
        "action": "verdict", "verdict": "supported", "reason": "Fixture", "ids": ["seed"],
        "correspondence": [],
        "transition": {"observation_id": "seed", "before_frame_id": "first", "after_frame_id": "later"},
    }
    assert not Draft202012Validator(_schema("verification")).is_valid(action)
    assert Draft202012Validator(_schema("verification", allow_transition=True)).is_valid(action)
