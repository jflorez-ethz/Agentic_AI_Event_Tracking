import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator
from google import genai

import probe


@pytest.mark.parametrize(("mode", "failure"), [("media", False), ("media", True),
                                                ("investigation", False), ("investigation", True),
                                                ("investigation", "MAX_TOKENS"),
                                                ("continuation", False), ("continuation", "MAX_TOKENS"),
                                                ("continuation", "unknown"), ("continuation", "overlimit"),
                                                ("continuation", "duplicate"), ("continuation", "archived"),
                                                ("continuation", "association"), ("continuation", "bad_anchor")])
def test_single_request_probe(tmp_path, monkeypatch, mode, failure):
    real_client = genai.Client
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.path == "/v1beta/models/gemini-3.6-flash:generateContent"
        body = json.loads(request.content)
        config = body["generationConfig"]
        parts = body["contents"][0]["parts"]
        if mode == "media":
            assert config["thinkingConfig"]["thinking_level"] == "HIGH"
            assert sum("inlineData" in p for p in parts) == 20
            answer = {"observations": []}
            finish = "MAX_TOKENS" if failure else "STOP"
        else:
            assert config["thinkingConfig"]["thinking_level"] == "HIGH"
            assert config["maxOutputTokens"] == 20480
            assert len(parts) == 1 and "text" in parts[0]
            context = json.loads(parts[0]["text"])
            ids = list(context["evidence"])
            assert context["initial_observation_count"] == 11
            assert context["max_candidates"] == 4
            if mode == "continuation":
                saved = json.loads(probe.CONTINUATION_RECORD.read_text())["analysis"]
                assert ids == [row["observation"]["id"] for row in saved["observations"]]
                for row in saved["observations"]:
                    obs, citation = row["observation"], row["citation"]
                    supplied = context["evidence"][obs["id"]]
                    assert supplied["description"] == obs["description"][:400]
                    assert supplied["interval"] == citation["interval"]
                    assert supplied["frame_ids"] == [frame["id"] for frame in citation["frames"]]
                assert context["last_tool_result"] == next(
                    row["details"] for row in saved["trace"] if row["actor"] == "investigation"
                    and row["action"] == "tool_result"
                )
                assert not context["additional_evidence_available"]
            else:
                assert len(ids) == 8 and context["additional_evidence_available"]
            branch, = (branch for branch in config["responseJsonSchema"]["anyOf"]
                       if "ids" in branch["properties"])
            assert branch["properties"]["ids"]["maxItems"] == 4
            assert branch["properties"]["ids"]["items"]["enum"] == ids
            associated, = (item["properties"] for item in branch["properties"]["dispositions"]["items"]["anyOf"]
                           if "correspondence" in item["properties"])
            pair_fields = associated["correspondence"]["properties"]
            assert pair_fields["status"]["enum"] == ["same_event"]
            assert pair_fields["shared_frame_id"]["type"] == "string"
            if failure is True:
                return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
            finish = "MAX_TOKENS" if failure == "MAX_TOKENS" else "STOP"
            answer = {"action": "delegate", "ids": ids[:4], "reason": "Fixture triage.",
                      "dispositions": [{"id": evidence_id, "status": "deferred", "reason": "Fixture budget."} for evidence_id in ids[4:]]}
            if failure == "unknown":
                answer["ids"][0] = "invented-observation"
            elif failure == "overlimit":
                answer["ids"] = ids[:5]
            elif failure == "duplicate":
                answer["ids"][1] = answer["ids"][0]
            elif failure in ("archived", "association", "bad_anchor"):
                live = Path(__file__).with_name("live.O6q6N8") / "continuation"
                answer = json.loads((live / "decision.json").read_text())
                old_schema = json.loads((live / "input.json").read_text())["schema"]
                assert Draft202012Validator(old_schema).is_valid(answer)
                validator = Draft202012Validator(config["responseJsonSchema"])
                assert not validator.is_valid(answer)
                if failure != "archived":
                    # Construct a positive fixture explicitly. Production never repairs a response.
                    assoc = answer["dispositions"][2]
                    assoc["id"] = assoc["correspondence"]["id"]
                    assert validator.is_valid(answer)
                    for path in (("id",), ("candidate_id",), ("correspondence", "id")):
                        record = assoc if len(path) == 1 else assoc[path[0]]
                        field = path[-1]
                        original = record[field]
                        record[field] = "unknown"
                        assert not validator.is_valid(answer)
                        record[field] = original
                    if failure == "bad_anchor":
                        assoc["correspondence"]["shared_frame_id"] = context["evidence"][ids[-1]]["frame_ids"][0]
                        assert validator.is_valid(answer)
        return httpx.Response(200, json={
            "candidates": [{"finishReason": finish, "content": {"parts": [{"text": json.dumps(answer)}]}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10, "thoughtsTokenCount": 5},
        })

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setenv("GEMINI_API_KEY", "mock-key")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    monkeypatch.setattr(genai, "Client", client)
    output = tmp_path / "result"
    with pytest.raises(SystemExit):
        probe.main([mode, "--live", "--output", str(output)])
    assert not requests
    auth = "--authorize-footage-transfer" if mode == "media" else "--authorize-observation-text-transfer"
    assert probe.main([mode, "--live", auth, "--output", str(output)]) == 0
    assert len(requests) == 1
    result = json.loads((output / "result.json").read_text())
    assert len(result["transport_attempts"]) == 1
    assert result["transport_attempts"][0]["http_status"] == (503 if mode == "investigation" and failure is True else 200)
    if mode == "media":
        config = json.loads(requests[0].content)["generationConfig"]
        assert config["maxOutputTokens"] == 8192
        assert dict(result["metadata"]["settings"])["max_output_tokens"] == 8192
        assert dict(result["metadata"]["usage"])["thoughts_token_count"] == 5
        assert result["validation"] == ("failed" if failure else "passed")
        if failure:
            assert result["error"]
        assert result["completion"] == {"candidate_count": 1, "finish_reasons": ["MAX_TOKENS" if failure else "STOP"]}
        assert result["normally_completed"] is not failure
    elif failure in ("unknown", "overlimit", "duplicate", "archived", "bad_anchor"):
        assert result["status"] == "failed" and result["delegated"] == []
        assert result["validation"] == "failed"
        expected = {
            "unknown": "Unknown or invalid evidence ID",
            "overlimit": "Evidence ID count 5 exceeds limit 4",
            "duplicate": "Duplicate evidence IDs",
            "archived": "Invalid, duplicate or unknown observation disposition",
            "bad_anchor": "Same-event assessment requires a shared cited source frame",
        }[failure]
        assert any(row["action"] == "rejected" and row["reason"] == expected for row in result["trace"])
    elif failure is True:
        assert result["status"] == "failed" and result["raw_response"] is None
    elif failure == "MAX_TOKENS":
        assert result["status"] == "failed" and result["delegated"] == []
        call, = result["calls"]
        assert call["status"] == "invalid_output"
        assert call["candidate_count"] == 1
        assert call["finish_reasons"] == ["MAX_TOKENS"]
        assert call["usage"]["thoughts_token_count"] == 5
    else:
        assert result["status"] == "valid_delegation"
        assert len(result["delegated"]) == 4 and json.loads(result["raw_response"])["dispositions"]
        if mode == "continuation":
            assert result["validation"] == "passed"
            assert len({item["id"] for item in result["dispositions"]}) == 11
            assert not any(row["action"] == "search" for row in result["trace"])
            if failure == "association":
                decision = json.loads((output / "decision.json").read_text())
                recorded = {record["id"]: record for record in result["dispositions"]}
                for association in (d for d in decision["dispositions"] if d["status"] == "associated"):
                    assert recorded[association["id"]] == association


@pytest.mark.parametrize(("case", "reason"), [
    ("archived", "Only a same-event assessment may assert a shared frame anchor"),
    ("different_without_anchor", "Association requires grounded same-event correspondence"),
    ("unresolved", "Association requires grounded same-event correspondence"),
    ("missing_same_event_anchor", "Same-event assessment requires a shared cited source frame"),
    ("mismatched_observation", "Invalid event correspondence reference or status"),
    ("foreign_anchor", "Same-event assessment requires a shared cited source frame"),
    ("deferred", None),
])
def test_archived_association_contract(tmp_path, case, reason):
    live = Path(__file__).with_name("live.bGCsdz") / "continuation"
    decision = json.loads((live / "decision.json").read_text())
    old_input = json.loads((live / "input.json").read_text())
    archived_result = json.loads((live / "result.json").read_text())
    assert Draft202012Validator(old_input["schema"]).is_valid(decision)
    assert json.loads(archived_result["raw_response"]) == decision
    analysis = json.loads(probe.CONTINUATION_RECORD.read_text())["analysis"]
    findings = probe.restore(analysis)
    by_id = {f.observation.id: f for f in findings}
    disposition = decision["dispositions"][3]
    pair = disposition["correspondence"]
    if case == "different_without_anchor":
        pair["shared_frame_id"] = None
    elif case == "unresolved":
        pair.update(status="unresolved", shared_frame_id=None)
    elif case == "missing_same_event_anchor":
        pair.update(status="same_event", shared_frame_id=None)
    elif case == "mismatched_observation":
        pair.update(status="same_event", id=decision["dispositions"][0]["id"])
    elif case == "foreign_anchor":
        foreign_frame = by_id[decision["ids"][0]].citation.frames[0]
        pair.update(status="same_event", shared_frame_id=foreign_frame.id)
    elif case == "deferred":
        decision["dispositions"][3] = {
            "id": disposition["id"], "status": "deferred",
            "reason": "Separate movement remains outside this verification queue.",
        }

    def decide(role, context):
        assert role == "investigation" and context == old_input["context"]
        schema = json.loads((tmp_path / "input.json").read_text())["schema"]
        assert Draft202012Validator(schema).is_valid(decision) == (
            case in {"deferred", "mismatched_observation", "foreign_anchor"}
        )
        return decision

    decide.raw_response = json.dumps(decision)
    decide.calls = []
    result = probe.investigate(
        probe.ingest(probe.SOURCE), findings, probe.Budget(**analysis["budget"]), decide, tmp_path,
        search=probe.archived_search(analysis),
    )
    if reason:
        assert result["validation"] == "failed" and not result["delegated"]
        assert result["trace"][-1]["reason"] == reason
    else:
        assert result["validation"] == "passed"
        assert result["delegated"] == decision["ids"]
        assert {record["id"] for record in result["dispositions"]} == set(by_id)
        for record in result["dispositions"]:
            if record["status"] == "associated":
                anchor = record["correspondence"]["shared_frame_id"]
                for identifier in (record["id"], record["candidate_id"]):
                    original = next(row["citation"] for row in analysis["observations"]
                                    if row["observation"]["id"] == identifier)
                    assert anchor in {frame.id for frame in by_id[identifier].citation.frames}
                    assert anchor in {frame["id"] for frame in original["frames"]}
