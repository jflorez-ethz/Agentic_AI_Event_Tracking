import json
import httpx
import pytest
from compare import CASES, RUN, execute, prepare


@pytest.mark.parametrize("case", CASES)
def test_only_sentence_differs(case):
    req = prepare(case)["A"]
    config = req["generationConfig"]
    assert config["maxOutputTokens"] == 20480 and config["thinkingConfig"]["thinking_level"] == "HIGH"
    c = json.loads(req["contents"][0]["parts"][0]["text"])
    rows = json.loads(RUN.read_text())["analysis"]["observations"]
    indices = range(8) if case == "full" else CASES[case]
    assert list(c["evidence"]) == [rows[i]["observation"]["id"] for i in indices]
    assert c["additional_evidence_available"] == (case == "full")
    assert c["max_candidates"] == 4 and c["independent_relational_tasks"]
    assert "unseen_observation_coverage" not in c


@pytest.mark.parametrize("arm", ["A", "B"])
def test_optional_search_then_valid_individual_plan(arm):
    def respond(request):
        c = json.loads(json.loads(request.content)["contents"][0]["parts"][0]["text"])
        if not c["last_tool_result"]:
            d = {"action": "search", "start_us": 10000000, "end_us": 20000000, "reason": "Check remaining evidence."}
        else:
            ids = list(c["evidence"])
            d = {"action": "delegate", "ids": [ids[1]], "reason": "Check this movement.",
                 "dispositions": [{"id": i, "status": "deferred", "reason": "Open."} for i in ids if i != ids[1]]}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(d)}]}}]})
    row = execute("full", arm, transport=httpx.MockTransport(respond), expected=prepare("full")[arm])
    assert row["valid"] and len(row["requests"]) == 2 and len(row["movements"]) == 1 and not row["relations"]


@pytest.mark.parametrize("over_budget", [False, True])
def test_displacement_and_shared_limit(over_budget):
    def respond(request):
        c = json.loads(json.loads(request.content)["contents"][0]["parts"][0]["text"])
        ids = list(c["evidence"])
        individual = [ids[i] for i in (1, 3, 5, 7)][:4 if over_budget else 3]
        d = {"action": "delegate", "ids": individual, "reason": "Allocate checks.",
             "relational_tasks": [{"observation_ids": [ids[3], ids[5]]}],
             "dispositions": [{"id": i, "status": "deferred", "reason": "Open."} for i in ids if i not in individual]}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(d)}]}}]})
    row = execute("full", "B", transport=httpx.MockTransport(respond))
    assert len(row["requests"]) == 1 and row["valid"] == (not over_budget)
    assert len(row["relations"]) == int(not over_budget)
