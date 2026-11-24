import base64
import hashlib
import json

import httpx
from google import genai
import pytest

from security_augmented.gemini import _png
from security_augmented.video import _decode, _run, ingest
from security_augmented.workflow import main


def make_video(source):
    _run(
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=96x64:r=5:d=8",
        "-vf", "drawbox=x=30:y=30:w=25:h=20:color=white:t=fill:enable='gte(t,2)*lt(t,6)'",
        "-c:v", "ffv1", str(source),
    )


def test_new_video_cli_requires_separate_transfer_authorizations(tmp_path):
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path / "video.mkv"), "--live", "--output", str(tmp_path / "run"),
              "--authorize-observation-text-transfer"])
    assert error.value.code == 2
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(("false_positive", "expanded_budget", "failure"), [
    (False, False, None), (True, False, None), (False, True, None),
    (False, False, "media"), (False, False, "verification"),
])
def test_new_video_to_report_and_query_without_archive(
    tmp_path, monkeypatch, false_positive, expanded_budget, failure,
):
    pytest.importorskip("langgraph")
    source = tmp_path / "block.mkv"
    make_video(source)
    video = ingest(source)
    ground_truth = list(_decode(video, (9, 10, 29, 30)))
    pixel = (35 * video.width + 35) * 3
    assert [frame[pixel] for frame in ground_truth] == [0, 255, 255, 0]
    assert [float(video.time_at_pts(video.frame_pts[i])) for i in (9, 10, 29, 30)] == [1.8, 2.0, 5.8, 6.0]
    output = tmp_path / "result"
    sent = []
    real_client = genai.Client

    def respond(request):
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        media = [p["inlineData"].get("mimeType", p["inlineData"].get("mime_type")) for p in parts if "inlineData" in p]
        sent.append(media)
        if media:
            assert "gemini-fixture-video" in request.url.path
            if len(sent) == 2:
                # Deliberately miss the visible disappearance at 6 seconds.
                value = {"observations": [{
                    "category": "person_enters_area", "description": "A person enters.",
                    "visibility_limits": "Synthetic scene.", "uncertainty": "Unsupported fixture claim.",
                    "frame_labels": ["F2"], "clip_interval_us": [],
                }] if false_positive else []}
            else:
                if len(sent) == 5:
                    prompt = " ".join(p["text"] for p in parts if "text" in p)
                    assert "report only visible cues" in prompt
                    assert "identity across a visibility gap" in prompt
                    if failure == "media":
                        return httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]})
                value = {"observations": [{
                    "category": "object_placed", "description": "A white block appears on a black background.",
                    "visibility_limits": "Synthetic scene.", "uncertainty": "Transition occurs between frames.",
                    "frame_labels": ["F2", "F3"] if media[0] == "image/png" else [],
                    "clip_interval_us": [0, 2_000_000] if media[0] == "video/webm" else [],
                }]}
        else:
            assert "gemini-3.6-flash" in request.url.path
            context = json.loads(parts[0]["text"])
            if len(sent) == 3:
                value = {"action": "delegate", "ids": list(context["evidence"]), "dispositions": []}
            elif len(sent) == 4:
                config = body["generationConfig"]
                assert config["thinkingConfig"]["thinking_level"] == "HIGH"
                assert config["maxOutputTokens"] == 8192
                if failure == "verification":
                    return httpx.Response(200, json={
                        "candidates": [{"finishReason": "MAX_TOKENS"}],
                        "modelVersion": "gemini-3.6-flash",
                        "usageMetadata": {"promptTokenCount": 20, "thoughtsTokenCount": 8192},
                    })
                instructions = body["systemInstruction"]["parts"][0]["text"]
                assert "receives observations and source references" in instructions
                assert "same model is not independent confirmation" in instructions
                value = {"action": "inspect", "modality": "clip", "start_us": 1_000_000, "end_us": 3_000_000}
            elif len(sent) == 6:
                candidate = context["candidate_id"]
                assert context["last_tool_result"]["ids"]
                seed = context["evidence"][candidate]
                other_id, = set(context["evidence"]) - {candidate}
                other = context["evidence"][other_id]
                shared = sorted(set(seed["frame_ids"]) & set(other["frame_ids"]))
                value = {"action": "verdict", "ids": [candidate, other_id], "verdict": "supported",
                         "correspondence": [{
                             "id": other_id, "status": "same_event", "seed_quote": seed["description"],
                             "other_quote": other["description"], "shared_frame_id": shared[0],
                         }]}
            elif false_positive and len(sent) == 7:
                value = {"action": "verdict", "verdict": "insufficient", "ids": [context["candidate_id"]],
                         "correspondence": []}
            else:
                value = {"action": "report", "lead_id": context["findings"][0]["id"], "emphasis": "evidence"}
            value["reason"] = "Synthetic fixture decision."
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(value)}],
        }}]})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    monkeypatch.setenv("GEMINI_VIDEO_MODEL", "gemini-fixture-video")
    for role in ("INVESTIGATION", "VERIFICATION", "REPORTING"):
        monkeypatch.delenv(f"GEMINI_{role}_MODEL", raising=False)
    budget_args = [
        "--max-candidates", "4", "--max-inspections", "4",
        "--max-agent-calls", "14", "--max-verification-iterations", "4",
    ] if expanded_budget else []
    assert main([
        *budget_args,
        str(source), "--live", "--authorize-footage-transfer", "--authorize-observation-text-transfer",
        "--movement-only", "--frame-step-ms", "1000",
        "--output", str(output), "--max-initial-windows", "2", "--window-seconds", "4",
        "--question", "Was an object placed?", "--question", "Did anyone remove it?",
    ]) == 0
    result = json.loads((output / "analysis.json").read_text())
    analysis = result["analysis"]
    if failure == "verification":
        assert len(sent) == 4
        assert not analysis["timeline"]
        assert analysis["completion"]["verification"] == "failed"
        verification, = [call for call in result["role_calls"] if call["role"] == "verification"]
        assert verification["status"] == "invalid_output"
        assert verification["model_version"] == "gemini-3.6-flash"
        assert verification["thinking_level"] == "HIGH" and verification["max_output_tokens"] == 8192
        assert verification["candidate_count"] == 1 and verification["finish_reasons"] == ["MAX_TOKENS"]
        assert verification["usage"]["thoughts_token_count"] == 8192
        assert not any(item["phase"] == "targeted" for item in analysis["evidence"])
        return
    if failure == "media":
        assert len(sent) == 5
        assert not analysis["timeline"]
        assert analysis["completion"]["verification"] == "failed"
        failure, = [item for item in analysis["evidence"] if item["phase"] == "targeted"]
        assert failure["status"] == "failed" and not failure["coverage"]
        assert failure["failure_diagnostics"] == {"candidate_count": 1, "finish_reasons": ["MAX_TOKENS"]}
        assert any(item["action"] == "tool_failure" for item in analysis["trace"])
        return

    assert result["independent_relational_tasks"] is False
    assert len(sent) == 7 + false_positive
    assert sent[0] == sent[1] == ["image/png"] * 4
    assert sent[4] == ["video/webm"]
    assert len(result["role_calls"]) == 4 + false_positive
    assert sum(len(r["transport_attempts"]) for r in result["role_calls"]) == 4 + false_positive
    names = ("max_candidates", "max_inspections", "max_agent_calls", "max_verification_iterations")
    expected = (4, 4, 14, 4) if expanded_budget else (2, 2, 6, 3)
    assert tuple(analysis["budget"][name] for name in names) == expected
    assert result["max_physical_role_requests"] == 2 * expected[2]
    assert result["max_physical_media_requests"] == 2 + expected[1]
    assert result["max_physical_requests"] == 2 * expected[2] + 2 + expected[1]
    assert analysis["completion"]["investigation"] == "completed"
    assert analysis["completion"]["accounted_observations"] == 1 + false_positive
    assert {"start_us": 7_000_001, "end_us": 8_000_000} in analysis["coverage"]["uninspected"]
    assert analysis["coverage"]["examined"]
    if false_positive:
        assert analysis["unresolved"][0]["category"] == "person_enters_area"
    assert analysis["coverage"]["initial_scan"] == "completed"
    assert "does not establish absence" in result["answers"][1]["text"]
    placement, = analysis["timeline"]
    assert placement["category"] == "object_placed"
    assert placement["interval"] == {"start_us": 1_000_000, "end_us": 2_000_001}
    assert placement == result["answers"][0]["events"][0]
    assert all(c["video_id"] == analysis["video"]["id"] for c in placement["citations"])
    assert {c["modality"] for c in placement["citations"]} == {"frames", "clip"}
    cited = {f["display_index"]: f for c in placement["citations"] for f in c["frames"]}
    for index, pixels in zip(sorted(cited), _decode(video, tuple(sorted(cited))), strict=True):
        assert cited[index]["pts"] == video.frame_pts[index]
        assert cited[index]["rgb24_sha256"] == hashlib.sha256(pixels).hexdigest()
    assert all(c["inspection_id"] in (output / "report.md").read_text() for c in placement["citations"])
    assert any(item["action"] == "graph_transition" for item in analysis["trace"])



@pytest.mark.parametrize("invalid_citation", [False, True])
def test_unscanned_tail_and_rejected_citation_preserve_incomplete_status(tmp_path, invalid_citation):
    from security_augmented.observation import FrameReference, InferenceMetadata, Observation, ObservationResult
    from security_augmented.workflow import Budget, InspectionPlan, analyze_video

    source = tmp_path / "block.mkv"
    make_video(source)

    class Provider:
        def infer(self, request):
            metadata = InferenceMetadata("offline", "fixture", None, "1", "1")
            observations = ()
            if invalid_citation:
                observations = (Observation(
                    "fabricated", request.media.inspection.id, "object_placed", "A block appears.",
                    FrameReference(("unsubmitted-frame",)), "Synthetic fixture.", "Unknown.",
                ),)
            return ObservationResult(metadata, observations)

    def decide(role, context):
        if role == "investigation":
            return {"action": "delegate", "ids": [], "dispositions": [], "reason": "No valid observations."}
        assert role == "reporting"
        assert context["completion"]["initial_scan"] == ("failed" if invalid_citation else "partial")
        return {"action": "report", "lead_id": None, "emphasis": "uncertainty", "reason": "Summarize."}

    result = analyze_video(
        source, Provider(), budget=Budget(max_initial_windows=1), plan=InspectionPlan(window_us=4_000_000),
        decide=decide,
    )
    assert not result.timeline
    assert not result.observations
    assert result.coverage.initial_scan_end_us == 4_000_000
    assert result.coverage.uninspected[-1].end_us == 8_000_000
    assert result.completion["investigation"] == ("failed" if invalid_citation else "partial")
    assert "Uninspected time provides no evidence of absence" in result.report
    if invalid_citation:
        assert not result.coverage.examined
        assert result.evidence[0].failure_stage == "validation"


def test_incomplete_media_and_overlimit_delegation_are_diagnosed(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    pytest.importorskip("langgraph")
    from security_augmented.agents import AgentModels, GeminiDecider
    from security_augmented.gemini import GeminiAdapter
    from security_augmented.workflow import Budget, InspectionPlan, analyze_video

    source = tmp_path / "block.mkv"
    make_video(source)
    client = Mock()

    def response(data, finish="STOP"):
        return SimpleNamespace(text=json.dumps(data), candidates=[SimpleNamespace(finish_reason=finish)],
                               usage_metadata=SimpleNamespace(candidates_token_count=369, thoughts_token_count=3709))

    def observe(count):
        return response({"observations": [
            {"category": "person_moved", "description": f"Fixture observation {i}.",
             "visibility_limits": "Synthetic.", "uncertainty": "Fixture.", "frame_labels": ["F1"],
             "clip_interval_us": []} for i in range(count)
        ]})

    def choose(**kwargs):
        payload = json.loads(kwargs["contents"])
        branch, = kwargs["config"]["response_json_schema"]["anyOf"]
        assert branch["properties"]["ids"]["maxItems"] == 4
        return response({"action": "delegate", "ids": list(payload["evidence"]), "dispositions": [], "reason": "Fixture."})

    outcomes = iter([observe(3), response({"observations": []}, "MAX_TOKENS"), observe(2)])
    client.models.generate_content.side_effect = lambda **kw: (
        choose(**kw) if isinstance(kw["contents"], str) else next(outcomes)
    )
    adapter = GeminiAdapter(client=client)
    decide = GeminiDecider(adapter, AgentModels())
    result = analyze_video(
        source, adapter, budget=Budget(max_initial_windows=3, max_candidates=4, max_failures=1),
        plan=InspectionPlan(window_us=3_000_000), decide=decide, controller="langgraph",
    )
    assert [e.status for e in result.evidence] == ["success", "failed", "success"]
    failure = result.evidence[1]
    assert failure.inspection.frames and not failure.coverage
    assert failure.failure_diagnostics == {"candidate_count": 1, "finish_reasons": ["MAX_TOKENS"]}
    assert result.completion["initial_scan"] == "partial"
    assert result.completion["investigation"] == "failed"
    assert result.completion["verification"] == "not_started"
    assert result.completion["accounted_observations"] == 0
    assert result.completion["initial_observations"] == 5
    assert not result.timeline
    assert any(d.action == "rejected" and d.reason == "Evidence ID count 5 exceeds limit 4" for d in result.trace)
    assert len(decide.calls) == 1 and decide.calls[0]["finish_reasons"] == ["STOP"]


@pytest.mark.parametrize("targeted_failure", [None, "MAX_TOKENS", "UNAVAILABLE"])
def test_archived_scan_triggers_automatic_investigation_without_question(tmp_path, monkeypatch, targeted_failure):
    from pathlib import Path

    pytest.importorskip("langgraph")
    source = Path("data/raw/Meet_WalkSplit_pts.mp4")
    archive = Path("experiments/meet_walk_split_high.Cpby7p/run/analysis.json")
    recorded = json.loads(archive.read_text())["analysis"]
    windows = iter(recorded["evidence"])
    rows = recorded["observations"]
    expected_ids = {row["observation"]["id"] for row in rows}
    first_visibility = rows[0]["observation"]["id"]
    movement = rows[7]["observation"]["id"]
    action_order = []
    target_frame_counts = []
    real_client = genai.Client

    def response(value, finish_reason="STOP"):
        return httpx.Response(200, json={"candidates": [{
            "finishReason": finish_reason, "content": {"parts": [{"text": json.dumps(value)}]},
        }]})

    def respond(request):
        assert request.url.path.endswith("/gemini-3.6-flash:generateContent")
        body = json.loads(request.content)
        config = body["generationConfig"]
        parts = body["contents"][0]["parts"]
        images = [part for part in parts if "inlineData" in part]
        settings = (config["thinkingConfig"]["thinking_level"], config["maxOutputTokens"])
        if images:
            assert settings == ("HIGH", 8192)
            if not action_order or action_order[-1] == "scan":
                action_order.append("scan")
                window = next(windows)
                frames = window["inspection"]["frames"]
                assert len(images) == len(frames)
                labels = {frame["id"]: f"F{i}" for i, frame in enumerate(frames, 1)}
                observations = []
                for finding in window["findings"]:
                    obs = finding["observation"]
                    observations.append({
                        **{key: obs[key] for key in ("category", "description", "visibility_limits", "uncertainty")},
                        "frame_labels": [labels[identifier] for identifier in obs["evidence"]["frame_ids"]],
                        "clip_interval_us": [],
                    })
                return response({"observations": observations})
            action_order.append("targeted")
            target_frame_counts.append(len(images))
            if targeted_failure == "UNAVAILABLE":
                return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
            return response({"observations": []}, targeted_failure or "STOP")

        context = json.loads(parts[0]["text"])
        if "max_candidates" in context:
            assert settings == ("HIGH", 20480)
            assert context["initial_observation_count"] == 11
            assert context["max_candidates"] == 4
            if not context["last_tool_result"]:
                action_order.append("search")
                assert len(context["evidence"]) == 8 and context["additional_evidence_available"]
                return response({"action": "search", "start_us": 16_000_000, "end_us": 24_960_000,
                                 "reason": "Retrieve later observations before triage."})
            action_order.append("delegate")
            assert set(context["evidence"]) == expected_ids
            assert len(context["last_tool_result"]["ids"]) == 3
            assert not context["additional_evidence_available"]
            branch, = config["responseJsonSchema"]["anyOf"]
            assert branch["properties"]["ids"]["maxItems"] == 4
            selected = [first_visibility, movement]
            return response({"action": "delegate", "ids": selected, "reason": "Check early visibility and later movement.",
                             "dispositions": [
                                 {"id": identifier, "status": "deferred", "reason": "Outside these two checks."}
                                 for identifier in context["evidence"] if identifier not in selected
                             ]})

        if "candidate_id" in context:
            assert settings == ("HIGH", 8192)
            seed = context["candidate_id"]
            if seed == first_visibility:
                if context["last_tool_result"] is None:
                    action_order.append("inspect")
                    assert context["can_inspect_and_reconsider"]
                    from jsonschema import Draft202012Validator

                    action = {"action": "inspect", "modality": "frames", "start_us": 0, "end_us": 1_500_000,
                              "reason": "Look for a before/after visibility pair."}
                    schema = Draft202012Validator(config["responseJsonSchema"])
                    assert schema.is_valid(action) and schema.is_valid(action | {"sampling_step_ms": 500})
                    assert not schema.is_valid(action | {"sampling_step_ms": 250})
                    assert not schema.is_valid(action | {"modality": "clip", "sampling_step_ms": 250})
                    action.update(sampling_step_ms=250, visual_question="When is the person first visible?")
                    assert schema.is_valid(action)
                    return response(action)
                action_order.append("insufficient")
                assert context["last_tool_result"]["new_display_indices"] == [7, 19, 32]
                assert not context["fine_available"]
                assert not context["last_tool_result"]["ids"]
                return response({"action": "verdict", "ids": [seed], "verdict": "insufficient",
                                 "correspondence": [], "reason": "One cited frame cannot establish first visibility."})
            action_order.append("movement")
            assert seed == movement
            before, after = context["evidence"][seed]["frame_ids"][0], context["evidence"][seed]["frame_ids"][-1]
            return response({"action": "verdict", "ids": [seed], "verdict": "supported", "correspondence": [],
                             "reason": "The cited sequence describes movement across the tiled floor.",
                             "transition": {"observation_id": seed, "before_frame_id": before, "after_frame_id": after}})

        action_order.append("report")
        assert settings == ("HIGH", 8192)
        assert {finding["verdict"] for finding in context["findings"]} == {"supported", "insufficient"}
        return response({"action": "report", "lead_id": movement, "emphasis": "uncertainty",
                         "reason": "Summarize supported movement and unresolved visibility."})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    for role in ("VIDEO", "INVESTIGATION", "VERIFICATION", "REPORTING"):
        monkeypatch.setenv(f"GEMINI_{role}_MODEL", "gemini-3.6-flash")

    output = tmp_path / "automatic"
    assert main([
        str(source), "--live", "--authorize-footage-transfer", "--authorize-observation-text-transfer",
        "--frame-step-ms", "500", "--max-candidates", "4", "--max-inspections", "4",
        "--max-agent-calls", "14", "--max-verification-iterations", "4", "--output", str(output),
        # This scenario exercises Investigation's search path, which needs hidden observations.
        "--max-visible-observations", "8",
    ]) == 0
    result = json.loads((output / "analysis.json").read_text())
    analysis = result["analysis"]
    assert result["answers"] == []
    # No --max-initial-windows: "auto" scans the whole 25 s source in three 10 s windows.
    assert analysis["budget"]["max_initial_windows"] == 3
    assert result["max_physical_media_requests"] == 3 + 4
    # WalkSplit has no security observation: an empty review queue and a header-only labelling sheet.
    assert analysis["review"]["counts"]["needs_review"] == 0
    assert (output / "alerts.csv").read_text().splitlines() == [
        "alert_id,category,start_s,end_s,frames_to_review,operator_label,operator_note"]
    assert (output / "report.md").read_text().startswith("## Alertes à vérifier (0)")
    replayed = analysis["observations"]
    assert len(replayed) == len(rows) == 11
    for actual, archived in zip(replayed, rows, strict=True):
        assert actual["citation"] == archived["citation"]
        assert {k: v for k, v in actual["observation"].items() if k != "inference_metadata"} == {
            k: v for k, v in archived["observation"].items() if k != "inference_metadata"
        }
    assert analysis["completion"]["initial_scan"] == "completed"
    assert analysis["completion"]["accounted_observations"] == 11
    assert analysis["completion"]["delegated"] == 2
    assert analysis["completion"]["investigation"] == "partial"
    assert target_frame_counts == [6]
    targeted, = [entry for entry in analysis["evidence"] if entry["phase"] == "targeted"]
    assert targeted["inspection"]["frames"][::2] == recorded["evidence"][0]["inspection"]["frames"][:3]
    assert {"search", "tool_result", "delegate", "inspect", "verdict", "graph_transition"} <= {
        item["action"] for item in analysis["trace"]
    }
    expected_order = ["scan"] * 3 + ["search", "delegate", "inspect", "targeted"]
    if targeted_failure:
        assert action_order == expected_order
        assert targeted["status"] == "failed" and not targeted["coverage"]
        if targeted_failure == "MAX_TOKENS":
            assert targeted["failure_diagnostics"] == {"candidate_count": 1, "finish_reasons": ["MAX_TOKENS"]}
        else:
            assert targeted["failure_diagnostics"]["http_status"] == 503
        assert not analysis["timeline"] and analysis["completion"]["verification"] == "failed"
    else:
        assert action_order == expected_order + ["insufficient", "movement", "report"]
        assert analysis["completion"]["verification"] == "completed"
        supported, = analysis["timeline"]
        assert supported["observation_ids"] == [movement]
        assert any(event["observation_ids"] == [first_visibility] for event in analysis["unresolved"])
    report = (output / "report.md").read_text()
    assert "11/11 accounted for" in report
    assert "Finding remains unresolved" in report


@pytest.mark.parametrize("propose", [False, True])
def test_normal_video_cli_delegates_open_relational_task_and_can_abstain(tmp_path, monkeypatch, propose):
    """Exercise default live-mode wiring with real local frames and scripted SDK responses."""
    source = "data/raw/Meet_WalkSplit_pts.mp4"
    sent = []
    submitted_pngs = []
    real_client = genai.Client

    def respond(request):
        body = json.loads(request.content)
        schema = body["generationConfig"]["responseJsonSchema"]
        parts = body["contents"][0]["parts"]
        images = [part for part in parts if "inlineData" in part]
        if images:
            if not sent:
                assert len(images) == 2  # Initial scan remains at 500 ms.
                assert "relation" not in schema["properties"]
                sent.append("scan")
                value = {"observations": [
                    {"category": "person_moved", "description": description,
                     "visibility_limits": "Scripted for an interface test.", "uncertainty": "Unknown.",
                     "frame_labels": ["F1", "F2"], "clip_interval_us": []}
                    for description in ("First visible movement.", "Second visible movement.")
                ]}
            else:
                assert "relation" in schema["properties"]
                sent.append("targeted")
                assert len(images) == 3
                submitted_pngs.extend(base64.urlsafe_b64decode(part["inlineData"]["data"]) for part in images)
                assert "What can the visible paths establish?" in str(parts[0])
                relation = {"claim": "approach", "interval": {"start_us": 0, "end_us": 280001},
                            "distinct_paths": False, "nearby_frame_label": None,
                            "views": [{"frame_label": label, "marks": [{"x": x, "y": 50, "radius": 1} for x in xs]}
                                      for label, xs in [("F1", [20, 100]), ("F2", [40, 80])]]}
                value = {"observations": [], "relation": relation if propose else None}
        else:
            context = json.loads(parts[0]["text"])
            if "max_candidates" in context:
                sent.append("investigation")
                assert context["independent_relational_tasks"]
                ids = list(context["evidence"])
                scope = context["evidence"][ids[0]]["interval"]
                assert scope == {"start_us": 0, "end_us": 520001}
                value = {"action": "delegate", "ids": [], "relational_tasks": [{"observation_ids": ids}],
                         "dispositions": [{"id": i, "status": "deferred", "reason": "Separate lead."} for i in ids],
                         "reason": "Investigate the visible movements."}
            elif "relational_task" in context:
                if context["last_tool_result"] is None:
                    assert context["fine_available"] and context["sampling_steps_ms"] == [500, 250]
                    frame_branch, = [b for b in schema["anyOf"] if "sampling_step_ms" in b["properties"]]
                    assert frame_branch["properties"]["sampling_step_ms"]["enum"] == [500, 250]
                    assert "sampling_step_ms" not in frame_branch["required"]
                    sent.append("verify")
                    value = {"action": "inspect", "modality": "frames", "relational": True,
                             "start_us": 0, "end_us": 520001, "reason": "The textual leads are ambiguous.",
                             "sampling_step_ms": 250, "visual_question": "What can the visible paths establish?"}
                else:
                    sent.append("reconsider")
                    assert not context["fine_available"]
                    assert context["last_tool_result"]["new_display_indices"] == [7]
                    proposals = context["last_tool_result"]["relation_proposal_ids"]
                    assert len(proposals) == int(propose)
                    value = {"action": "relation_verdict", "verdict": "insufficient",
                             "reason": "The inspection left correspondence unresolved."}
                    if propose:
                        value.update(verdict="supported", relation_proposal_id=proposals[0])
            else:
                sent.append("report")
                value = {"action": "report", "lead_id": None, "emphasis": "uncertainty",
                         "reason": "Identify open questions."}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(value)}],
        }}]})

    def client(**kwargs):
        assert kwargs["http_options"].client_args["follow_redirects"] is False
        assert kwargs["http_options"].retry_options.attempts == 1
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    output = tmp_path / "relational"
    assert main([source, "--live", "--authorize-footage-transfer", "--authorize-observation-text-transfer",
                 "--max-initial-windows", "1", "--window-seconds", "1",
                 "--question", "What happened after the two people approached each other?", "--output", str(output)]) == 0
    result = json.loads((output / "analysis.json").read_text())
    video = ingest(source)
    assert submitted_pngs == [_png(rgb, video.width, video.height) for rgb in _decode(video, (0, 7, 13))]
    assert result["physical_requests"] == len(sent) == 6
    assert sent == ["scan", "investigation", "verify", "targeted", "reconsider", "report"]
    assert [attempt["http_status"] for attempt in result["media_attempts"]] == [200, 200]
    analysis = result["analysis"]
    task, = analysis["completion"]["relational_tasks"]
    assert task["status"] == ("supported" if propose else "unresolved")
    inspection = analysis["evidence"][-1]["inspection"]
    original = analysis["evidence"][0]["inspection"]["frames"]
    assert inspection["frames"][::2] == original
    assert inspection["requested_times_us"] == [0, 250000, 500000]
    new = inspection["frames"][1]
    assert new["display_index"] == 7 and new["source_time_us"] == 280000
    assert hashlib.sha256(_decode(ingest(source), (7,))[0]).hexdigest() == new["rgb24_sha256"]
    if propose:
        assert analysis["timeline"][0]["relation"]["claim"] == "approach"
        assert new["id"] in analysis["report"]
        assert result["answers"][0]["anchor"]["citations"][0]["frames"][-1] == new
    else:
        assert not analysis["timeline"] and "Relational task unresolved" in analysis["report"]
        assert result["answers"][0]["anchor"] is None
    assert analysis["coverage"]["plan"]["frame_step_us"] == 500_000
    assert analysis["completion"]["investigation"] == "partial"


def test_shared_client_media_budget_is_independent_and_capped():
    from security_augmented.agents import PhysicalRequestLimit, RoleHTTPBudget

    budget = RoleHTTPBudget(1, media_limit=1)
    budget.before_send(None)
    with pytest.raises(PhysicalRequestLimit, match="media"):
        budget.before_send(None)
    budget.attempts = []
    budget.before_send(None)
    with pytest.raises(PhysicalRequestLimit):
        budget.before_send(None)
    assert budget.sent == len(budget.media_attempts) == 1
