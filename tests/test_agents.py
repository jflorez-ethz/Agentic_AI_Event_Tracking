from conftest import anchored_verdict
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from security_augmented.workflow import analyze_archive

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "data/raw/LeftBag.mpg"
ARCHIVES = tuple(ROOT / "experiments" / name for name in (
    "e1_comparison_001", "e1_comparison_001_a_clip_retry_001",
))


class AgentDecisionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = analyze_archive(VIDEO, ARCHIVES)
        cls.placed, cls.uncertain = [f.observation.id for f in cls.baseline.observations]
        cls.clip = cls.baseline.timeline[0].observation_ids[1]

    def analyze(self, scripts, trace_context=None, **kwargs):
        def decide(role, context):
            if trace_context is not None:
                trace_context.append((role, context))
            action = scripts[role].pop(0)
            return {"reason": "Fixture decision based on available evidence.", **anchored_verdict(action, context.get("evidence", {}), context.get("candidate_id"))}

        with patch("security_augmented.workflow._load_archive", return_value=kwargs.pop("evidence", self.baseline.evidence)):
            return analyze_archive(VIDEO, ARCHIVES, decide=decide, **kwargs)

    def test_context_dependent_inspection_and_baseline_comparison(self):
        scripts = {
            "investigation": [
                {"action": "search", "start_us": 36_000_000, "end_us": 40_000_000},
                {"action": "delegate", "ids": [self.placed, self.uncertain]},
            ],
            "verification": [
                {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000},
                {"action": "verdict", "verdict": "supported", "ids": [self.placed, self.clip]},
                {"action": "verdict", "verdict": "insufficient", "ids": [self.uncertain]},
            ],
            "reporting": [{"action": "report", "lead_id": self.placed, "emphasis": "uncertainty"}],
        }
        context = []
        result = self.analyze(scripts, context)
        self.assertEqual(result.timeline[0].observation_ids, self.baseline.timeline[0].observation_ids)
        self.assertEqual(result.unresolved[0].verdict, "insufficient")
        self.assertEqual(sum(d.action == "inspect" for d in result.trace), 1)
        self.assertEqual(sum(d.action == "inspect" for d in self.baseline.trace), 2)
        verification_context = [data for role, data in context if role == "verification"]
        self.assertNotIn(self.clip, verification_context[0]["evidence"])
        self.assertIn(self.clip, verification_context[1]["evidence"])
        self.assertIn(self.clip, verification_context[2]["evidence"])
        self.assertIn("Lead finding", result.report)
        self.assertFalse(result.ask("Was the bag abandoned?").events)

    def test_invalid_delegation_and_reporting_fall_back_safely(self):
        result = self.analyze({
            "investigation": [{"action": "delegate", "ids": ["fabricated"]}],
            "reporting": [{"action": "report", "lead_id": "fabricated", "emphasis": "evidence"}],
        })
        self.assertFalse(result.timeline)
        self.assertEqual(sum(d.action == "rejected" for d in result.trace), 2)
        self.assertIn("No supported events", result.report)

    def test_repeated_inspection_and_missing_support(self):
        inspect = {"action": "inspect", "modality": "frames", "start_us": 36_000_000, "end_us": 40_000_000}
        result = self.analyze({
            "investigation": [{"action": "delegate", "ids": [self.placed]}],
            "verification": [inspect, inspect, {"action": "verdict", "verdict": "supported", "ids": [self.placed]}],
            "reporting": [{"action": "report", "lead_id": None, "emphasis": "uncertainty"}],
        })
        self.assertFalse(result.timeline)
        self.assertEqual(len(result.unresolved), 2)
        self.assertEqual(sum(d.action == "inspect" for d in result.trace), 1)
        self.assertTrue(any(d.action == "rejected" for d in result.trace))

    def test_invalid_tool_and_fabricated_citation_do_not_run_or_verify(self):
        result = self.analyze({
            "investigation": [{"action": "delegate", "ids": [self.placed]}],
            "verification": [
                {"action": "inspect", "modality": "shell", "start_us": 0, "end_us": 1},
                {"action": "verdict", "verdict": "supported", "ids": [self.placed, "fabricated"]},
            ],
            "reporting": [{"action": "report", "lead_id": None, "emphasis": "evidence"}],
        })
        self.assertFalse(result.timeline)
        self.assertFalse(any(d.action == "inspect" for d in result.trace))
        self.assertEqual(result.unresolved[0].observation_ids, (self.placed,))

    def test_conflicting_evidence_is_preserved_and_blocks_support(self):
        from dataclasses import replace

        archive = self.baseline.evidence
        entry = next(e for e in archive if any(f.observation.id == self.clip for f in e.findings))
        finding = entry.findings[0]
        conflict = replace(finding, observation=replace(
            finding.observation, id="opposing-observation", category="object_removed",
        ))
        evidence = (*archive, replace(entry, findings=(conflict,)))
        result = self.analyze({
            "investigation": [{"action": "delegate", "ids": [self.placed]}],
            "verification": [
                {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000},
                {"action": "verdict", "verdict": "supported", "ids": [self.placed, self.clip]},
            ],
            "reporting": [{"action": "report", "lead_id": None, "emphasis": "uncertainty"}],
        }, evidence=evidence)
        self.assertFalse(result.timeline)
        self.assertIn("opposing-observation", result.unresolved[0].observation_ids)

    def test_provider_failure_is_traced_and_unsupported_not_promoted(self):
        evidence = tuple(e for e in self.baseline.evidence if e.modality != "clip" or e.status == "failed")
        context = []
        result = self.analyze({
            "investigation": [{"action": "delegate", "ids": [self.placed]}],
            "verification": [
                {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000},
                {"action": "verdict", "verdict": "unsupported", "ids": [self.placed]},
            ],
            "reporting": [{"action": "report", "lead_id": None, "emphasis": "evidence"}],
        }, context, evidence=evidence)
        self.assertFalse(result.timeline)
        self.assertTrue(any(d.action == "tool_failure" for d in result.trace))
        self.assertEqual(context[2][1]["last_tool_result"]["status"], "failed")
        self.assertEqual(result.unresolved[0].verdict, "unsupported")


    def test_repackaged_identical_frames_do_not_add_corroboration(self):
        from dataclasses import replace

        seed = self.baseline.observations[0]
        duplicate = replace(
            seed, observation=replace(seed.observation, id="duplicate", inspection_id="other"),
            citation=replace(seed.citation, inspection_id="other", modality="clip"),
        )
        entry = next(e for e in self.baseline.evidence if any(f.observation.id == self.clip for f in e.findings))
        result = self.analyze({
            "investigation": [{"action": "delegate", "ids": [self.placed]}],
            "verification": [
                {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000},
                {"action": "verdict", "verdict": "supported", "ids": [self.placed, "duplicate"]},
            ],
            "reporting": [{"action": "report", "lead_id": None, "emphasis": "uncertainty"}],
        }, evidence=(self.baseline.evidence + (replace(entry, findings=(duplicate,)),)))
        self.assertFalse(result.timeline)
        self.assertTrue(any("corroborating" in d.reason for d in result.trace if d.action == "rejected"))


class GeminiDecisionTests(TestCase):
    def test_model_configuration_and_json_transport(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from security_augmented.agents import AgentModels, GeminiDecider
        from security_augmented.gemini import GeminiAdapter

        with patch.dict("os.environ", {
            "GEMINI_INVESTIGATION_MODEL": "i", "GEMINI_VERIFICATION_MODEL": "v",
            "GEMINI_REPORTING_MODEL": "r", "GEMINI_VIDEO_MODEL": "media",
        }):
            models = AgentModels.from_env()
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason="STOP")],
            text='{"action":"delegate","ids":[],"reason":"No credible event"}',
        )
        decider = GeminiDecider(GeminiAdapter(client=client, model=models.video), models)
        self.assertEqual(decider("investigation", {"evidence": {}})["ids"], [])
        self.assertEqual(client.models.generate_content.call_args.kwargs["model"], "i")
        self.assertEqual(models.verification, "v")
        self.assertEqual(models.reporting, "r")
        self.assertEqual(decider.adapter.model, "media")
        self.assertEqual(client.models.generate_content.call_args.kwargs["config"]["response_mime_type"], "application/json")

    def test_role_transport_needs_authorization_and_redacts_client_error(self):
        from unittest.mock import Mock

        from security_augmented.agents import AgentModels, GeminiDecider
        from security_augmented.contracts import VideoError
        from security_augmented.gemini import GeminiAdapter

        with self.assertRaisesRegex(VideoError, "authorization"):
            GeminiDecider.from_env(authorized=False)
        client = Mock()
        client.models.generate_content.side_effect = RuntimeError("private-key")
        decider = GeminiDecider(GeminiAdapter(client=client), AgentModels())
        with self.assertRaises(VideoError) as result:
            decider("verification", {})
        self.assertNotIn("private-key", str(result.exception))

    def test_controller_enforces_zero_decision_budget(self):
        from unittest.mock import Mock

        from security_augmented.workflow import Budget

        decide = Mock()
        # An empty replay selection is enough to exercise the hard decision limit.
        with patch("security_augmented.workflow._load_archive", return_value=()):
            result = analyze_archive(VIDEO, ARCHIVES, decide=decide, budget=Budget(max_agent_calls=0))
        decide.assert_not_called()
        self.assertFalse(result.timeline)
        self.assertIn("No supported events", result.report)
        self.assertTrue(any(d.action == "budget_exhausted" for d in result.trace))
