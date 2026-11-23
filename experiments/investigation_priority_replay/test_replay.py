import json

import httpx
import pytest

import replay


def reply(value):
    return httpx.Response(200, json={"modelVersion": replay.MODEL, "usageMetadata": {
        "promptTokenCount": 100, "candidatesTokenCount": 10, "thoughtsTokenCount": 15, "totalTokenCount": 125},
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(value)}]}}]})


def archived_delegation(name):
    rows = json.loads(replay.CASES[name][0].read_text())["analysis"]["completion"]["observation_dispositions"]
    return {"action": "delegate", "reason": "Archived live triage.",
            "ids": [r["id"] for r in rows if r["status"] == "delegated"],
            "dispositions": [{k: r[k] for k in ("id", "status", "reason")} for r in rows if r["status"] != "delegated"]}


def test_replay_sends_text_only_and_reports_target(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "offline")
    bodies = []

    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert not any("inlineData" in p or "inline_data" in p for c in body["contents"] for p in c["parts"])
        context = json.loads(body["contents"][0]["parts"][0]["text"])
        name = "leftbox" if any(e["category"] == "object_placed" for e in context["evidence"].values()) else "fall"
        # The model repeats its archived triage even after feedback; the runtime must still check the box.
        return reply(archived_delegation(name))

    with pytest.raises(SystemExit):
        replay.main(["--repeats", "1", "--output", str(tmp_path / "x")], transport=httpx.MockTransport(respond))
    assert not bodies and not (tmp_path / "x").exists()

    out = tmp_path / "run"
    assert replay.main(["--authorize-observation-text-transfer", "--repeats", "1", "--output", str(out)],
                       transport=httpx.MockTransport(respond)) == 0
    results = json.loads((out / "results.json").read_text())
    by_video = {r["video"]: r for r in results}
    assert by_video["leftbox"]["target_delegated"] and by_video["leftbox"]["feedback_round"]
    assert by_video["leftbox"]["runtime_enforced"] and by_video["leftbox"]["physical_requests"] == 2
    assert by_video["fall"]["target_delegated"] and not by_video["fall"]["feedback_round"]
    assert all(r["media_requests"] == 0 for r in results) and len(bodies) == 3
    assert "Estimated cost" in capsys.readouterr().out
