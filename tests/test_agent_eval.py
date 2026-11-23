from conftest import anchored_verdict, archive_descriptions
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from security_augmented.agent_eval import EVAL_BUDGET, evaluate_archive, main
from security_augmented.agents import AgentModels, GeminiDecider
from security_augmented.gemini import GeminiAdapter
from security_augmented.workflow import analyze_archive

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "data/raw/LeftBag.mpg"
ARCHIVES = tuple(ROOT / "experiments" / name for name in (
    "e1_comparison_001", "e1_comparison_001_a_clip_retry_001",
))


class ArchiveEvaluationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = analyze_archive(VIDEO, ARCHIVES)

    def test_archive_only_comparison_and_call_metrics(self):
        placed, unresolved = (f.observation.id for f in self.baseline.observations)
        clip = self.baseline.timeline[0].observation_ids[1]
        import json
        actions = [
            {"action": "delegate", "ids": [placed, unresolved]},
            {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000},
            {"action": "verdict", "verdict": "supported", "ids": [placed, clip]},
            {"action": "verdict", "verdict": "insufficient", "ids": [unresolved]},
            {"action": "report", "lead_id": placed, "emphasis": "evidence"},
        ]
        client = Mock()
        client.models.generate_content.side_effect = [
            SimpleNamespace(
                candidates=[SimpleNamespace(finish_reason="STOP")],
                text=json.dumps({**anchored_verdict(action, archive_descriptions(self.baseline)), "reason": "Evidence test."}),
                model_version="fixture",
                usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5, total_token_count=15),
            )
            for action in actions
        ]
        decider = GeminiDecider(GeminiAdapter(client=client), AgentModels())
        with patch("security_augmented.agent_eval._load_archive", return_value=self.baseline.evidence) as load:
            paired = evaluate_archive(VIDEO, ARCHIVES, decide=decider)
        load.assert_called_once()
        self.assertEqual(client.models.generate_content.call_count, 5)
        for call, recorded in zip(client.models.generate_content.call_args_list, paired["role_calls"], strict=True):
            args = call.kwargs
            expected = {"investigation": ("HIGH", 20480), "verification": ("HIGH", 8192),
                        "reporting": ("HIGH", 8192)}[recorded["role"]]
            config = args["config"]
            self.assertEqual((config["thinking_config"]["thinking_level"], config["max_output_tokens"]), expected)
            self.assertEqual(args["model"], "gemini-3.5-flash-lite")
            self.assertIsInstance(args["contents"], str)
            self.assertNotIn("inline_data", args["contents"])
            self.assertNotIn(str(VIDEO), args["contents"])
        self.assertEqual(paired["evaluation"]["gemini"]["placement_count"], 1)
        self.assertEqual(paired["evaluation"]["gemini"]["unresolved_count"], 1)
        self.assertEqual(paired["evaluation"]["gemini"]["tokens"]["total_token_count"], 75)
        self.assertEqual(paired["evaluation"]["baseline"]["placement_count"], 1)
        self.assertEqual(paired["evaluation"]["gemini"]["unresolved_count"], 1)
        self.assertTrue(all(row["elapsed_ms"] >= 0 for row in paired["role_calls"]))

    def test_malformed_response_stops_hosted_actions(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason="STOP")], text="invalid JSON",
        )
        decider = GeminiDecider(GeminiAdapter(client=client), AgentModels())
        with patch("security_augmented.agent_eval._load_archive", return_value=self.baseline.evidence):
            paired = evaluate_archive(VIDEO, ARCHIVES, decide=decider)
        client.models.generate_content.assert_called_once()
        self.assertEqual(paired["role_calls"][0]["status"], "invalid_output")
        self.assertFalse(paired["gemini"]["timeline"])
        self.assertEqual(EVAL_BUDGET.max_failures, 1)

    def test_live_cli_requires_explicit_data_authorization(self):
        with patch("security_augmented.agent_eval.GeminiDecider.from_env") as load:
            with self.assertRaises(SystemExit):
                main([str(VIDEO), "--archive", str(ARCHIVES[0]), "--output", "/tmp/unused-agent-eval", "--live"])
            load.assert_not_called()

    def test_live_cli_uses_independent_role_and_video_models(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp, patch.dict("os.environ", {
            "GEMINI_INVESTIGATION_MODEL": "investigation-model",
            "GEMINI_VERIFICATION_MODEL": "verification-model",
            "GEMINI_REPORTING_MODEL": "reporting-model",
            "GEMINI_VIDEO_MODEL": "unchanged-video-model",
        }), patch("security_augmented.agent_eval.GeminiDecider.from_env") as factory, patch(
            "security_augmented.agent_eval.evaluate_archive", return_value={"evaluation": {}},
        ):
            self.assertEqual(main([
                str(VIDEO), "--archive", str(ARCHIVES[0]), "--output", str(Path(temp) / "run"),
                "--controller", "langgraph", "--live", "--authorize-observation-text-transfer",
            ]), 0)
            factory.assert_called_once_with(
                authorized=True, max_physical_requests=12,
                models=AgentModels("investigation-model", "verification-model", "reporting-model", "unchanged-video-model"),
            )
            self.assertEqual(EVAL_BUDGET.max_agent_calls, 6)

    def test_repeated_tool_request_is_rejected_and_no_further_calls_are_made(self):
        import json

        placed = self.baseline.observations[0].observation.id
        unresolved = self.baseline.observations[1].observation.id
        inspect = {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000}
        client = Mock()
        client.models.generate_content.side_effect = [
            SimpleNamespace(
                candidates=[SimpleNamespace(finish_reason="STOP")],
                text=json.dumps({**anchored_verdict(action, archive_descriptions(self.baseline)), "reason": "Fixture"}),
            )
            for action in (
                {"action": "delegate", "ids": [placed, unresolved]},
                inspect, {"action": "verdict", "verdict": "insufficient", "ids": [placed]},
                inspect,
            )
        ]
        decider = GeminiDecider(GeminiAdapter(client=client), AgentModels())
        with patch("security_augmented.agent_eval._load_archive", return_value=self.baseline.evidence):
            result = evaluate_archive(VIDEO, ARCHIVES, decide=decider)
        client.models.generate_content.assert_called()
        self.assertEqual(client.models.generate_content.call_count, 4)
        self.assertEqual(result["evaluation"]["gemini"]["tool_calls"], 1)
        self.assertTrue(any("repeated" in d["reason"] for d in result["gemini"]["trace"]))
        self.assertTrue(any("failure limit" in d["reason"] for d in result["gemini"]["trace"]))

    def test_langgraph_live_cli_text_only_direct_and_recovery_paths(self):
        import json
        from tempfile import TemporaryDirectory

        import pytest
        pytest.importorskip("langgraph")
        try:
            import httpx2 as httpx
        except ImportError:
            import httpx
        from google import genai

        seed, uncertain = (finding.observation.id for finding in self.baseline.observations)
        clip = self.baseline.timeline[0].observation_ids[1]
        real_client = genai.Client
        for recovery, failing_call in ((False, None), (True, None), (False, 1), (True, 3), (False, 4)):
            with self.subTest(recovery=recovery, failing_call=failing_call), TemporaryDirectory() as temp:
                actions = [
                    {"action": "delegate", "ids": [seed, uncertain]},
                    *([{"action": "verdict", "verdict": "supported", "ids": [seed]}] if recovery else []),
                    {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000},
                    {"action": "verdict", "verdict": "supported", "ids": [seed, clip]},
                    {"action": "verdict", "verdict": "insufficient", "ids": [uncertain]},
                    {"action": "report", "lead_id": seed, "emphasis": "uncertainty"},
                ]
                contexts = []
                sent = []
                failed_once = False

                def respond(req):
                    nonlocal failed_once
                    body = json.loads(req.content)
                    self.assertEqual(req.url.path, "/v1beta/models/gemini-3.5-flash-lite:generateContent")
                    parts = [p for c in body["contents"] for p in c["parts"]]
                    self.assertEqual(len(parts), 1)
                    self.assertEqual(set(parts[0]), {"text"})
                    self.assertNotIn(str(VIDEO), parts[0]["text"])
                    sent.append(req.content)
                    logical_call = 1 + len(contexts)
                    if logical_call == failing_call or (logical_call == 2 and not failed_once):
                        failed_once = True
                        return httpx.Response(503, json={"error": {
                            "code": 503, "status": "UNAVAILABLE", "message": "fixture unavailable",
                        }})
                    contexts.append(json.loads(parts[0]["text"]))
                    action = {**anchored_verdict(actions.pop(0), contexts[-1].get("evidence", {}), contexts[-1].get("candidate_id")), "reason": "Fixture justification."}
                    return httpx.Response(200, json={
                        "candidates": [{"finishReason": "STOP", "content": {
                            "parts": [{"text": json.dumps(action)}],
                        }}],
                        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
                    })

                output = Path(temp) / "evaluation"

                def client(**kwargs):
                    kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
                    return real_client(**kwargs)

                with patch.object(genai, "Client", side_effect=client), patch.dict(
                    "os.environ", {"GEMINI_API_KEY": "offline-fixture", "GOOGLE_GENAI_HTTP_CLIENT": httpx.__name__},
                ), patch("security_augmented.agents.time.sleep"), patch(
                    "security_augmented.agent_eval._load_archive", return_value=self.baseline.evidence,
                ), patch("security_augmented.gemini.GeminiAdapter.infer", side_effect=AssertionError("perception called")):
                    self.assertEqual(main([
                        str(VIDEO), "--archive", str(ARCHIVES[0]), "--archive", str(ARCHIVES[1]),
                        "--output", str(output), "--controller", "langgraph", "--live",
                        "--authorize-observation-text-transfer",
                    ]), 0)

                result = json.loads((output / "evaluation.json").read_text())
                self.assertEqual(result["controllers"]["gemini"], "langgraph")
                calls = result["role_calls"]
                metrics = result["evaluation"]["gemini"]
                self.assertEqual(metrics["physical_http_attempts"], len(sent))
                self.assertEqual(result["transport_policy"]["max_physical_requests"], 12)
                if failing_call is not None:
                    self.assertEqual(len(calls), failing_call)
                    self.assertEqual(calls[-1]["status"], "api_error")
                    self.assertEqual([a["http_status"] for a in calls[-1]["transport_attempts"]], [503, 503])
                    self.assertEqual(sent[-2], sent[-1])
                    self.assertEqual(metrics["tool_calls"], int(failing_call == 4))
                    self.assertEqual(metrics["placement_count"], int(failing_call == 4))
                    completion = result["gemini"]["completion"]
                    self.assertEqual(completion["investigation"], "failed" if failing_call == 1 else "partial")
                    self.assertEqual(completion["completed_checks"], int(failing_call == 4))
                    self.assertEqual(completion["verification"], {1: "not_started", 3: "failed", 4: "partial"}[failing_call])
                    self.assertTrue((output / "gemini-report.md").is_file())
                    continue
                self.assertEqual([a["http_status"] for a in calls[1]["transport_attempts"]], [503, 200])
                self.assertEqual(sent[1], sent[2])
                self.assertEqual(metrics["tool_calls"], 1)
                self.assertEqual(result["evaluation"]["gemini"]["model_calls"], 6 if recovery else 5)
                self.assertEqual(result["evaluation"]["gemini"]["placement_count"], 1)
                self.assertTrue(result["evaluation"]["gemini"]["ambiguous_handling_retained"])
                self.assertFalse(result["evaluation"]["gemini"]["invalid_citation_events"])
                self.assertFalse(actions)
                trace = result["gemini"]["trace"]
                edges = [item["details"] for item in trace if item["action"] == "graph_transition"]
                self.assertEqual(edges[0], {"from": "START", "to": "investigate"})
                self.assertEqual(edges[-1], {"from": "report", "to": "END"})
                self.assertEqual(any(item["action"] == "recovery" for item in trace), recovery)
                if recovery:
                    self.assertEqual(contexts[2]["validation_feedback"]["code"], "missing_corroboration")
                self.assertEqual(contexts[-1]["findings"][0]["verdict"], "supported")


def test_role_http_retry_policy(monkeypatch):
    import pytest
    import httpx
    from google import genai
    from security_augmented.contracts import VideoError

    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    for statuses, limit, outcome in (
        ([200], 2, "received"),
        ([503, 200], 2, "received"),
        ([503, 503], 2, "api_error"),
        ([400], 2, "api_error"),
        ([503], 1, "physical_budget_exhausted"),
    ):
        sent = []

        def respond(request):
            sent.append(request.content)
            status = statuses[len(sent) - 1]
            if status != 200:
                return httpx.Response(status, json={"error": {
                    "code": status, "status": "UNAVAILABLE" if status == 503 else "INVALID_ARGUMENT",
                    "message": "sensitive fixture error body",
                }})
            return httpx.Response(200, json={"candidates": [{
                "finishReason": "STOP", "content": {"parts": [{"text": '{"action":"delegate","ids":[],"reason":"None visible"}'}]},
            }]})

        def client(**kwargs):
            kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
            return real_client(**kwargs)

        with patch.object(genai, "Client", side_effect=client), patch("security_augmented.agents.time.sleep") as sleep:
            decide = GeminiDecider.from_env(authorized=True, max_physical_requests=limit)
            if outcome == "received":
                assert decide("investigation", {})["action"] == "delegate"
            else:
                with pytest.raises(VideoError):
                    decide("investigation", {})
            call, = decide.calls
            assert call["status"] == outcome
            assert [a["http_status"] for a in call["transport_attempts"]] == statuses
            assert len(sent) == len(statuses)
            assert len(set(sent)) == 1
            assert sleep.call_count == len(statuses) - 1
            if sleep.called:
                assert 1 <= sleep.call_args.args[0] <= 2
            assert "sensitive fixture error body" not in str(call)
            if limit == 1:
                with pytest.raises(VideoError):
                    decide("verification", {})
                assert decide.calls[-1]["transport_attempts"] == []
                assert len(sent) == 1
            decide.adapter.client.close()
