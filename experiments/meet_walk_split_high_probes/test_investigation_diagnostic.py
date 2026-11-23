import json

import httpx
import pytest
from google import genai
from jsonschema import Draft202012Validator

import investigation_diagnostic as probe


@pytest.mark.parametrize("http_status", [400, 503])
def test_capture_provider_details_without_retry_or_request_contents(tmp_path, monkeypatch, http_status):
    calls = []
    real_client = genai.Client
    sent_context = probe.load_probe()[0]
    secret = "offline-key-secret"
    private = next(iter(sent_context["evidence"].values()))["description"]

    def respond(request):
        calls.append(request.url.path)
        body = json.loads(request.content)
        assert json.loads(body["contents"][0]["parts"][0]["text"]) == sent_context
        config = body["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        assert config["thinkingConfig"]["thinking_level"] == "HIGH"
        assert config["maxOutputTokens"] == 20480
        schema = config["responseJsonSchema"]
        Draft202012Validator.check_schema(schema)
        branch = schema["anyOf"][-1]
        assert "relational_tasks" not in branch["required"]
        assert "ids" in branch["required"]
        return httpx.Response(http_status, json={"error": {
            "code": http_status, "status": "INVALID_ARGUMENT" if http_status == 400 else "UNAVAILABLE",
            "message": f"Bad parameter candidateCount. API key: {secret}. Echo: {private}",
            "details": [{
                "@type": "type.googleapis.com/google.rpc.BadRequest",
                "fieldViolations": [{"field": "generationConfig.candidateCount",
                                     "description": f"Value invalid. Echo: {private}"}],
            }, {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "MOCK_REASON",
                "domain": "googleapis.com", "metadata": {"private": secret}},
                {"@type": "other", "data": secret}],
        }})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    out = tmp_path / "run"
    assert probe.main(["--output", str(out), "--authorize-observation-text-transfer"]) == 0
    result = json.loads((out / "result.json").read_text())
    assert result["physical_http_requests"] == len(calls) == 1
    assert result["decision_validation"] == {"status": "not_reached"}
    error, = result["provider_errors"]
    assert error["request_number"] == 1 and error["http_status"] == error["code"] == http_status
    assert "Bad parameter candidateCount" in error["message"]
    assert error["field_violations"][0]["field"] == "generationConfig.candidateCount"
    assert error["error_info"] == [{"reason": "MOCK_REASON", "domain": "googleapis.com"}]
    assert secret not in json.dumps(result) and private not in json.dumps(result)
    assert "retry_delay_seconds" not in json.dumps(result)


def test_live_probe_requires_explicit_authorization(tmp_path):
    with pytest.raises(SystemExit) as exc:
        probe.main(["--output", str(tmp_path / "forbidden")])
    assert exc.value.code == 2


def test_local_schema_delta_retains_existing_delegation_and_optional_task():
    from security_augmented.agents import _decision_schema

    context = probe.load_probe()[0]
    baseline = _decision_schema("investigation", context | {"independent_relational_tasks": False})
    extended = _decision_schema("investigation", context)
    validator = Draft202012Validator(extended)
    first, second, *_ = context["evidence"]
    movement = {"action": "delegate", "ids": [first], "dispositions": [], "reason": "Check movement."}
    assert validator.is_valid(movement)
    assert validator.is_valid(movement | {"relational_tasks": [{"observation_ids": [first, second]}]})
    assert not validator.is_valid(movement | {"relational_tasks": [{"observation_ids": [first, "unknown"]}]})
    extended["anyOf"][-1]["properties"].pop("relational_tasks")
    assert extended == baseline


@pytest.mark.parametrize("valid", [True, False])
def test_completed_response_is_validated_without_executing_it(tmp_path, monkeypatch, valid):
    real_client = genai.Client
    count = []

    def respond(request):
        count.append(request.url.path)
        text = json.dumps({"action": "search", "start_us": 14_000_000,
                           "end_us": 23_000_000 if valid else -1,
                           "reason": "Do not persist this decision text."})
        return httpx.Response(200, json={"candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    out = tmp_path / "success"
    probe.main(["--output", str(out), "--authorize-observation-text-transfer"])
    result = json.loads((out / "result.json").read_text())
    assert result["physical_http_requests"] == len(count) == 1
    assert result["provider_errors"] == []
    assert result["decision_action"] == "search"
    assert result["decision_validation"]["status"] == ("accepted" if valid else "rejected")
    assert result["role_call"]["finish_reasons"] == ["STOP"]
    assert "Do not persist" not in json.dumps(result)


def test_task_array_constraints_move_to_runtime_only():
    from security_augmented.agents import _decision_schema

    context, _ = probe.load_probe()
    schema = _decision_schema("investigation", context)
    branch = schema["anyOf"][-1]["properties"]["relational_tasks"]
    assert "maxItems" not in branch
    assert "minItems" not in branch["items"]["properties"]["observation_ids"]
    assert len(branch["items"]["properties"]["observation_ids"]["items"]["enum"]) == len(context["evidence"])


@pytest.mark.parametrize(("case", "expected"), [
    ("movement", "accepted"), ("task", "accepted"), ("empty_tasks", "accepted"),
    ("short", "rejected"), ("duplicate", "rejected"), ("unknown", "rejected"),
    ("excessive", "rejected"), ("bad_action", "rejected"), ("nonoverlapping", "rejected"),
])
def test_runtime_decisions_after_provider_relaxation(case, expected):
    from security_augmented.agents import _decision_schema

    context, _ = probe.load_probe()
    seed = next(k for k in context["evidence"] if k.startswith("observation-ac83682fb5"))
    peer = next(k for k in context["evidence"] if k.startswith("observation-83b23ba3db"))
    earlier = next(k for k in context["evidence"] if k.startswith("observation-3bfb1c56bb"))
    rows = [{"observation_ids": ids} for ids in {
        "empty_tasks": [], "short": [[seed]], "duplicate": [[seed, seed]], "unknown": [[seed, "unknown"]],
        "excessive": [[seed, peer]] * 4, "nonoverlapping": [[seed, earlier]],
    }.get(case, [[seed, peer]])]
    action = {
        "action": "inspect" if case == "bad_action" else "delegate", "ids": [seed], "reason": "Check observed activity.",
        "dispositions": [{"id": identifier, "status": "deferred", "reason": "Pending independent check."}
                         for identifier in (peer, earlier)],
        **({"relational_tasks": rows} if case != "movement" else {}),
    }
    schema = Draft202012Validator(_decision_schema("investigation", context))
    assert schema.is_valid(action) == (case not in ("unknown", "bad_action"))
    assert probe.validate_decision(action, context)["status"] == expected
