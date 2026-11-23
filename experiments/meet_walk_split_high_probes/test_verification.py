import hashlib
import json

from google import genai
import httpx
import pytest

import verification
from security_augmented.video import _decode, ingest


@pytest.mark.parametrize("report_finish", ["STOP", "MAX_TOKENS"])
def test_archived_handoff_runs_verification_and_reporting_offline(tmp_path, monkeypatch, report_finish):
    pytest.importorskip("langgraph")
    decision = json.loads((verification.HANDOFF / "decision.json").read_text())
    candidates = decision["ids"]
    real_client = genai.Client
    steps = []
    seen = []

    def respond(request):
        assert request.url.path.endswith("/gemini-3.6-flash:generateContent")
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        config = body["generationConfig"]
        settings = config["thinkingConfig"]["thinking_level"], config["maxOutputTokens"]
        finish = "STOP"
        if any("inlineData" in part for part in parts):
            assert settings == ("HIGH", 8192)
            steps.append("targeted_media")
            action = {"observations": [{
                "category": "insufficient_evidence", "description": "The supplied views do not establish continuity.",
                "visibility_limits": "The view is distant.", "uncertainty": "Person correspondence is uncertain.",
                "frame_labels": ["F1", "F2"], "clip_interval_us": [],
            }]}
        else:
            context = json.loads(parts[0]["text"])
            if "candidate_id" in context:
                assert settings == ("HIGH", 8192)
                seed = context["candidate_id"]
                assert seed in candidates
                if seed not in seen:
                    seen.append(seed)
                if seed == candidates[0] and context["last_tool_result"] is None:
                    steps.append("inspect")
                    assert context["can_inspect_and_reconsider"]
                    action = {"action": "inspect", "modality": "frames",
                              "start_us": 9_100_000, "end_us": 10_000_000}
                else:
                    steps.append("verdict")
                    if seed == candidates[0]:
                        new_id, = context["last_tool_result"]["ids"]
                        assert context["evidence"][new_id]["frame_ids"]
                        assert context["evidence"][new_id]["category"] == "insufficient_evidence"
                    action = {"action": "verdict", "ids": [seed], "verdict": "insufficient", "correspondence": []}
            else:
                steps.append("report")
                assert settings == ("HIGH", 8192)
                finish = report_finish
                assert context["completion"]["completed_checks"] == 4
                assert {f["id"] for f in context["findings"]} >= set(candidates)
                assert {f["verdict"] for f in context["findings"]} == {"insufficient"}
                action = {"action": "report", "lead_id": None, "emphasis": "uncertainty"}
            action["reason"] = "Offline fixture preserves uncertainty."
        return httpx.Response(200, json={
            "candidates": [{"finishReason": finish, "content": {"parts": [{"text": json.dumps(action)}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 5, "thoughtsTokenCount": 2},
        })

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    output = tmp_path / "verification"
    args = ["--output", str(output), "--authorize-observation-text-transfer"]
    with pytest.raises(SystemExit):
        verification.main(args)
    assert not output.exists()
    assert verification.main([*args, "--authorize-footage-transfer"]) == 0

    result = json.loads((output / "result.json").read_text())
    assert set(seen) == set(candidates)
    assert steps == ["inspect", "targeted_media", *["verdict"] * 4, "report"]
    assert result["physical_requests"] == len(steps) == 7
    assert result["media_attempts"] == [{"request_number": 1, "http_status": 200}]
    assert result["max_physical_role_requests"] == 24 and result["max_physical_media_requests"] == 4
    assert result["completion"]["accounted_observations"] == 11
    assert result["completion"]["verification"] == "completed"
    assert result["completion"]["completed_checks"] == 4
    assert [row["role"] for row in result["role_calls"]] == ["verification"] * 5 + ["reporting"]
    reporting = result["role_calls"][-1]
    assert reporting["model"] == "gemini-3.6-flash"
    assert reporting["thinking_level"] == "HIGH" and reporting["max_output_tokens"] == 8192
    assert reporting["candidate_count"] == 1 and reporting["finish_reasons"] == [report_finish]
    assert reporting["usage"]["thoughts_token_count"] == 2
    assert reporting["status"] == ("received" if report_finish == "STOP" else "invalid_output")
    assert any(row["action"] == "model_failure" and row["actor"] == "reporting"
               for row in result["trace"]) == (report_finish == "MAX_TOKENS")
    spec = json.loads(verification.CONTINUATION_RECORD.read_text())["analysis"]
    original = {row["observation"]["id"]: row["citation"] for row in spec["observations"]}
    assert all(event["citations"] == [original[event["observation_ids"][0]]] for event in result["events"])
    target, = result["targeted_evidence"]
    finding, = target["findings"]
    frames = finding["citation"]["frames"]
    video = ingest(verification.SOURCE)
    pixels = _decode(video, tuple(frame["display_index"] for frame in frames))
    for frame, rgb in zip(frames, pixels, strict=True):
        assert video.frame_pts[frame["display_index"]] == frame["pts"]
        assert hashlib.sha256(rgb).hexdigest() == frame["rgb24_sha256"]
    report = (output / "report.md").read_text()
    assert "4/4 checks completed" in report and "No supported events" in report
    assert any(row["action"] == "graph_transition" for row in result["trace"])


def test_report_preserves_archived_verification_rationales(monkeypatch):
    from dataclasses import replace

    from security_augmented.agents import AgentRun
    from security_augmented.contracts import FrameEvidence, Interval
    from security_augmented.workflow import Budget, Citation, Event

    archive = verification.HANDOFF.parent.parent / "verification.Uk6X57" / "run"
    result = json.loads((archive / "result.json").read_text())
    events = tuple(Event(
        row["category"], Interval(**row["interval"]), row["verdict"], row["reason"], tuple(row["observation_ids"]),
        tuple(Citation(c["video_id"], c["inspection_id"], c["modality"], Interval(**c["interval"]),
                       tuple(FrameEvidence(**frame) for frame in c["frames"])) for c in row["citations"]),
    ) for row in result["events"])
    reporting = result["decisions"][-1]["decision"]
    calls = []

    def decide(role, context):
        assert role == "reporting"
        calls.append(context)
        return reporting

    agent = AgentRun(ingest(verification.SOURCE), decide, lambda *_: (), Budget(**result["budget"]), [])
    monkeypatch.setattr(agent, "completion", lambda: result["completion"])
    before = (archive / "report.md").read_text()
    after = agent.report(events)
    prefix = "  - Verification rationale (model assessment): "
    rationale_lines = [line for line in after.splitlines() if line.startswith(prefix)]
    assert len(calls) == 1
    # The legacy report used one transition explanation for all unresolved items.
    for event in events:
        if event.verdict == "insufficient":
            before = before.replace("A source-grounded before/after pair was not established.",
                                    f"Recorded reason: {event.reason}", 1)
    assert "".join(line for line in after.splitlines(keepends=True) if not line.startswith(prefix)) == before
    expected = [e.reason for e in events if e.verdict == "supported"]
    assert len(set(expected)) == 4
    assert rationale_lines == [prefix + reason for reason in expected]
    assert after.count("Finding remains unresolved.") == 7
    assert "joining the other walking individual" not in after

    # Missing rationale leaves the category label, interval, and citation intact.
    first = next(e for e in events if e.verdict == "supported")
    fallback = agent.report((replace(first, reason=" "),))
    assert prefix not in fallback
    assert "A person moved within view. supported" in fallback
    assert first.citations[0].inspection_id in fallback

    # A rationale can contain a relationship the event schema does not validate.
    unverified = agent.report((replace(first, reason="The two people may have joined.\n# Unverified"),))
    assert "A person moved within view. supported" in unverified
    assert [line for line in unverified.splitlines() if "may have joined" in line] == [
        prefix + "The two people may have joined. # Unverified"
    ]
