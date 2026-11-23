"""Offline tests for the two one-request diagnostics."""
import json

import httpx
import pytest
from google import genai

import isolated_relational as probe


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    path = tmp_path_factory.mktemp("isolated") / "plan"
    probe.main(["prepare", "--output", str(path)])
    return path


@pytest.mark.parametrize(("kind", "flag"), [("verification", "--authorize-observation-text-transfer"),
                                              ("perception", "--authorize-footage-transfer")])
def test_probes_require_separate_authorization(tmp_path, prepared, kind, flag):
    args = ["run", kind, "--prepared", str(prepared), "--output", str(tmp_path / "result")]
    with pytest.raises(SystemExit) as err:
        other = ("--authorize-footage-transfer" if flag == "--authorize-observation-text-transfer"
                 else "--authorize-observation-text-transfer")
        probe.main(args + [other])
    assert err.value.code == 2


@pytest.mark.parametrize("status", [200, 503, "duplicate", "archive_verdict"])
def test_verification_never_dispatches_selected_inspection(prepared, tmp_path, monkeypatch, status):
    saved = json.loads(probe.ARCHIVE.read_text())
    expected = next(x["context"] for x in saved["decisions"] if x["candidate_id"] == probe.CANDIDATE)
    calls = []

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        assert json.loads(body["contents"][0]["parts"][0]["text"]) == expected
        action = {"action": "inspect", "modality": "frames", "relational": True, "start_us": 10_000_000,
                  "end_us": 13_000_001, "reason": "The relative paths remain unclear.",
                  "visual_question": "How does the projected spacing change?"}
        if status == "archive_verdict":
            action = next(x["decision"] for x in saved["decisions"] if x["candidate_id"] == probe.CANDIDATE)
        if status == "duplicate":
            action.update(start_us=3_520_000, end_us=9_520_001)
        return response(503 if status == 503 else 200, action)

    install_transport(monkeypatch, respond)
    out = tmp_path / "out"
    assert probe.main(["run", "verification", "--prepared", str(prepared), "--output", str(out),
                       "--authorize-observation-text-transfer"]) == 0
    result = json.loads((out / "result.json").read_text())
    assert result["physical_http_requests"] == len(calls) == 1
    if status == 200:
        assert result["decision_audit"]["status"] == "relational_inspection_eligible"
    elif status == "archive_verdict":
        assert result["decision_audit"]["status"] == "movement_verdict"
    elif status == "duplicate":
        assert result["decision_audit"]["code"] == "inspection_outside_candidate"
    else:
        assert result["status"] == "failed"


@pytest.mark.parametrize("variant", ["proposal", "abstain", "invalid", "unavailable"])
def test_fixed_media_has_seven_source_frames(prepared, tmp_path, monkeypatch, variant):
    manifest = json.loads((prepared / "perception.json").read_text())
    assert [f["display_index"] for f in manifest["inspection"]["frames"]] == [250, 263, 275, 288, 300, 313, 325]
    calls = []

    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        assert sum("inlineData" in part for part in parts) == 7
        assert "reception seating" not in json.dumps(parts)
        relation = {
            "claim": "visible_divergence", "interval": {"start_us": 10_000_000, "end_us": 13_000_001},
            "views": [{"frame_label": label, "marks": [{"x": x, "y": 50, "radius": 1}
                                                        for x in points]}
                      for label, points in (("F1", (40, 55)), ("F7" if variant != "invalid" else "F99", (10, 80)))],
            "distinct_paths": True, "nearby_frame_label": None,
        }
        return response(503 if variant == "unavailable" else 200,
                        {"observations": [], "relation": None if variant == "abstain" else relation})

    install_transport(monkeypatch, respond)
    out = tmp_path / "out"
    assert probe.main(["run", "perception", "--prepared", str(prepared), "--output", str(out),
                       "--authorize-footage-transfer"]) == 0
    result = json.loads((out / "result.json").read_text())
    assert result["physical_http_requests"] == len(calls) == 1
    assert result["proposal_status"] == {"proposal": "supported", "abstain": "abstained",
                                          "invalid": "invalid", "unavailable": "not_reached"}[variant]


def response(status, action):
    if status != 200:
        return httpx.Response(status, json={"error": {"code": status, "status": "UNAVAILABLE", "message": "mock"}})
    return httpx.Response(200, json={"candidates": [
        {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(action)}]}}]})


def install_transport(monkeypatch, respond):
    real_client = genai.Client

    def client(**kwargs):
        options = kwargs["http_options"].client_args
        if "transport" not in options:
            options["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
