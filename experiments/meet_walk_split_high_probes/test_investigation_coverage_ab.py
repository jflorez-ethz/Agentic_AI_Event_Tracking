import json
from types import SimpleNamespace

import investigation_coverage_ab as probe


def finding(identifier, start, end):
    return SimpleNamespace(observation=SimpleNamespace(id=identifier),
                           citation=SimpleNamespace(interval=SimpleNamespace(start_us=start, end_us=end)))


def test_coverage_counts_only_unseen_and_merges_touching_ranges():
    evidence = [finding("a", 8, 10), finding("b", 0, 4), finding("c", 4, 6),
                finding("d", 5, 7), finding("visible", 7, 8)]
    assert probe.coverage(evidence, {"visible"}) == [
        {"start_us": 0, "end_us": 7, "observation_count": 3},
        {"start_us": 8, "end_us": 10, "observation_count": 1},
    ]
    assert probe.coverage(evidence, {"a", "b", "c", "d", "visible"}) == []


def test_archived_replay_and_sdk_diff():
    requests, result = probe.prepare()
    a, b = (requests[arm] for arm in ("A", "B"))
    original = json.loads(a["contents"][0]["parts"][0]["text"])
    extra = [
        {"start_us": 16_000_000, "end_us": 19_520_001, "observation_count": 2},
        {"start_us": 20_000_000, "end_us": 24_520_001, "observation_count": 1},
    ]
    assert result["request_diff"] == {"added_context_field": probe.FIELD, "value": extra}
    a["contents"][0]["parts"][0]["text"] = b["contents"][0]["parts"][0]["text"]
    assert a == b
    assert json.loads(b["contents"][0]["parts"][0]["text"]) == original | {probe.FIELD: extra}
    assert a["generationConfig"]["maxOutputTokens"] == 16384
    assert a["generationConfig"]["thinkingConfig"]["thinking_level"] == "HIGH"
    replay = result["replay"]
    assert len(replay["delegated_ids"]) == 4
    assert {i for row in replay["scripted_search_checks"] for i in row["result"]["ids"]} == set(replay["omitted_ids"])


def test_no_unseen_keeps_search_unavailable_in_both_sdk_requests():
    prior = json.loads(probe.RUN.read_text())
    archived = prior["decisions"][0]
    context = archived["context"] | {"additional_evidence_available": False, "initial_observation_count": 8}
    models = probe.AgentModels(**prior["models"])
    a = probe.capture_request(context, archived["decision"], models)
    b = probe.capture_request(context | {probe.FIELD: []}, archived["decision"], models)
    schema = a["generationConfig"]["responseJsonSchema"]
    assert schema == b["generationConfig"]["responseJsonSchema"]
    assert '"search"' not in json.dumps(schema)


def test_live_pair_with_mock_provider(tmp_path, monkeypatch):
    prior = json.loads(probe.RUN.read_text())
    original = prior["decisions"][0]["decision"]
    seen = []
    real_client = probe.genai.Client

    def respond(request):
        body = json.loads(request.content)
        context = json.loads(body["contents"][0]["parts"][0]["text"])
        seen.append(context)
        assert request.url.path.endswith("/gemini-3.6-flash:generateContent")
        if context["last_tool_result"] is None:
            decision = {"action": "search", "start_us": 16_000_000, "end_us": 24_520_001,
                        "reason": "Check later observations."}
        else:
            decision = original | {"dispositions": original["dispositions"] + [
                {"id": identifier, "status": "deferred", "reason": "No slot remaining."}
                for identifier in context["last_tool_result"]["ids"]
            ]}
        return probe.httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(decision)}]}}],
            "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 10, "thoughtsTokenCount": 22},
        })

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = probe.httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(probe.genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    for arm in "AB":
        probe.main(["--live-arm", arm, "--pair-dir", str(tmp_path), "--authorize-observation-text-transfer"])
    comparison = probe.compare(tmp_path)
    assert len(seen) == 4
    assert seen[2].pop(probe.FIELD)
    assert seen[3].pop(probe.FIELD) == []
    assert seen[:2] == seen[2:]
    for arm in "AB":
        record = comparison[arm]
        assert record["physical_requests"] == 2
        assert record["slots_used"] == 4
        assert len(record["retrieved_ids"]) == 3
        assert not record["omitted_ids"]
        assert record["role_calls"][0]["usage"]["thoughts_token_count"] == 22
        raw = json.loads((tmp_path / arm / "result.json").read_text())["physical_requests"][0]["raw_response"]
        assert json.loads(raw)["candidates"][0]["finishReason"] == "STOP"


def test_live_requires_explicit_authorization(tmp_path):
    import pytest

    with pytest.raises(SystemExit) as error:
        probe.main(["--live-arm", "A", "--pair-dir", str(tmp_path)])
    assert error.value.code == 2
    assert not list(tmp_path.iterdir())


def test_transport_failure_does_not_retry(tmp_path, monkeypatch):
    attempts = []
    real_client = probe.genai.Client

    def respond(request):
        attempts.append(request.url.path)
        return probe.httpx.Response(503, json={"error": {"code": 503, "message": "Unavailable"}})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = probe.httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(probe.genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    probe.main(["--live-arm", "A", "--pair-dir", str(tmp_path), "--authorize-observation-text-transfer"])
    result = json.loads((tmp_path / "A" / "result.json").read_text())
    assert result["status"] == "no_valid_delegation"
    assert len(attempts) == len(result["physical_requests"]) == 1
    assert result["physical_requests"][0]["http_status"] == 503
