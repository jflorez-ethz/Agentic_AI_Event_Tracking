from conftest import anchored_verdict
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pytest

pytest.importorskip("langgraph")

from security_augmented.agent_eval import EVAL_BUDGET
from security_augmented.contracts import VideoError
from security_augmented.workflow import analyze_archive

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "data/raw/LeftBag.mpg"
ARCHIVES = tuple(ROOT / "experiments" / name for name in (
    "e1_comparison_001", "e1_comparison_001_a_clip_retry_001",
))
BUDGET = replace(EVAL_BUDGET, max_verification_iterations=3)


class GraphWorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = analyze_archive(VIDEO, ARCHIVES)
        cls.seed = cls.baseline.observations[0].observation.id
        cls.clip = cls.baseline.timeline[0].observation_ids[1]

    def analyze(self, verification, *, controller="langgraph", budget=BUDGET, evidence=None):
        calls = []
        def decide(role, context):
            calls.append((role, context))
            if role == "investigation":
                return {"action": "delegate", "ids": [self.seed], "reason": "Inspect placement."}
            if role == "reporting":
                return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Summarize."}
            action = next(steps)
            if isinstance(action, Exception):
                raise action
            return {**anchored_verdict(action, context.get("evidence", {}), context.get("candidate_id")),
                    "reason": "Assess cited source evidence."}

        steps = iter(verification)
        with patch("security_augmented.workflow._load_archive", return_value=evidence or self.baseline.evidence):
            result = analyze_archive(VIDEO, ARCHIVES, decide=decide, budget=budget, controller=controller)
        return result, calls

    def supported(self, *ids):
        return {"action": "verdict", "verdict": "supported", "ids": [self.seed, *ids]}

    def inspect(self):
        return {"action": "inspect", "modality": "clip", "start_us": 36_000_000, "end_us": 40_000_000}

    def test_graph_recovers_where_original_stops(self):
        actions = [self.supported(), self.inspect(), self.supported(self.clip)]
        original, original_calls = self.analyze(actions, controller="python")
        graph, graph_calls = self.analyze(actions)
        self.assertFalse(original.timeline)
        self.assertEqual(len(original_calls), 2)
        self.assertEqual(graph.timeline, (replace(
            self.baseline.timeline[0], reason="Assess cited source evidence.",
        ),))
        self.assertEqual(graph_calls[2][1]["validation_feedback"]["code"], "missing_corroboration")
        self.assertIn(self.clip, graph_calls[3][1]["evidence"])
        self.assertEqual(graph_calls[-1][1]["findings"][0]["verdict"], "supported")
        self.assertEqual(sum(d.action == "inspect" for d in graph.trace), 1)
        self.assertTrue(any(d.action == "recovery" for d in graph.trace))

    def test_archived_placement_with_silently_omitted_handling(self):
        result, _ = self.analyze([self.inspect(), self.supported(self.clip)])
        self.assertEqual(len(result.timeline), 1)
        self.assertEqual(len(result.timeline[0].citations), 2)
        ambiguous = self.baseline.observations[1]
        self.assertEqual(result.unresolved[0].citations, (ambiguous.citation,))
        self.assertEqual(result.completion["verification"], "completed")
        self.assertEqual(result.completion["investigation"], "partial")
        self.assertEqual(result.completion["accounted_observations"], 1)
        self.assertFalse(result.completion["triage_complete"])
        self.assertIn("1/1 checks completed", result.report)
        self.assertIn("1/2 accounted for", result.report)
        self.assertFalse(result.ask("Was the object abandoned?").events)

    def test_direct_support_and_invalid_citation(self):
        good, _ = self.analyze([self.inspect(), self.supported(self.clip)])
        self.assertEqual(len(good.timeline), 1)
        bad, calls = self.analyze([self.supported("fabricated")])
        self.assertFalse(bad.timeline)
        self.assertEqual([role for role, _ in calls], ["investigation", "verification", "reporting"])
        self.assertEqual(bad.completion["completed_checks"], 0)
        self.assertTrue(any(d.action == "verdict_rejected" for d in bad.trace))
        self.assertFalse(any(d.action == "recovery" for d in bad.trace))

    def test_missing_corroboration_and_budget_exhaustion(self):
        for budget in (BUDGET, replace(BUDGET, max_agent_calls=3), replace(BUDGET, max_recoveries=0)):
            with self.subTest(budget=budget):
                result, calls = self.analyze([self.supported(), self.supported()], budget=budget)
                self.assertFalse(result.timeline)
                self.assertEqual(result.unresolved[0].verdict, "insufficient")
                self.assertLessEqual(len(calls), budget.max_agent_calls)
                self.assertLessEqual(sum(d.action == "recovery" for d in result.trace), budget.max_recoveries)

    def test_repeated_inspection_and_api_failure_terminate(self):
        repeated, calls = self.analyze(
            [self.inspect(), self.inspect(), self.inspect()],
            budget=replace(BUDGET, max_agent_calls=7),
        )
        self.assertFalse(repeated.timeline)
        self.assertEqual(sum(d.action == "inspect" for d in repeated.trace), 1)
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[3][1]["validation_feedback"]["code"], "inspection_repeated")
        failure, calls = self.analyze([VideoError("Offline API fixture")])
        self.assertFalse(failure.timeline)
        self.assertEqual(len(calls), 2)
        self.assertTrue(any(d.action == "model_failure" for d in failure.trace))

    def test_conflict_and_tool_failure_are_preserved(self):
        archive = self.baseline.evidence
        entry = next(e for e in archive if any(f.observation.id == self.clip for f in e.findings))
        finding = entry.findings[0]
        conflict = replace(finding, observation=replace(
            finding.observation, id="conflict", category="object_removed",
        ))
        result, _ = self.analyze(
            [self.inspect(), self.supported(self.clip)],
            evidence=(*archive, replace(entry, findings=(conflict,))),
        )
        self.assertFalse(result.timeline)
        self.assertIn("conflict", result.unresolved[0].observation_ids)
        result, _ = self.analyze([self.inspect()], evidence=tuple(e for e in archive if e.modality != "clip" or e.status == "failed"))
        self.assertFalse(result.timeline)
        self.assertTrue(any(d.action == "tool_failure" for d in result.trace))

    def test_empty_lookup_after_recovery_leaves_finding_unresolved(self):
        evidence = tuple(
            e for e in self.baseline.evidence
            if e.modality != "clip" or (e.status == "success" and not e.findings)
        )
        result, calls = self.analyze([
            self.supported(), self.inspect(),
            {"action": "verdict", "verdict": "unsupported", "ids": [self.seed]},
        ], evidence=evidence)
        self.assertEqual(calls[3][1]["last_tool_result"]["ids"], [])
        self.assertEqual(result.unresolved[0].verdict, "insufficient")
        self.assertFalse(result.timeline)

    def test_model_failure_before_delegation_is_distinct_from_empty(self):
        def decide(role, context):
            if role == "investigation":
                raise VideoError("API fixture")
            raise AssertionError("Terminal failure must stop further model calls")

        with patch("security_augmented.workflow._load_archive", return_value=self.baseline.evidence):
            result = analyze_archive(VIDEO, ARCHIVES, decide=decide, budget=BUDGET, controller="langgraph")
        self.assertEqual(result.completion["investigation"], "failed")
        self.assertFalse(result.completion["intentional_empty_delegation"])
        self.assertIn("investigation is incomplete", result.report)

        def empty(role, context):
            if role == "investigation":
                return {
                    "action": "delegate", "ids": [], "reason": "No candidates within synthetic scope.",
                    "dispositions": [
                        {"id": i, "status": "excluded", "reason": "Outside the fixture's scope."}
                        for i in context["evidence"]
                    ],
                }
            return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Report scope."}

        with patch("security_augmented.workflow._load_archive", return_value=self.baseline.evidence):
            result = analyze_archive(VIDEO, ARCHIVES, decide=empty, budget=BUDGET, controller="langgraph")
        self.assertEqual(result.completion["investigation"], "completed")
        self.assertTrue(result.completion["intentional_empty_delegation"])

    def test_failure_during_recovery_remains_unfinished(self):
        result, calls = self.analyze([self.supported(), VideoError("Offline API failure")])
        self.assertEqual(calls[-1][1]["validation_feedback"]["code"], "missing_corroboration")
        self.assertEqual(result.completion["completed_checks"], 0)
        self.assertEqual(result.completion["verification"], "failed")
        self.assertIn("Unfinished checks", result.report)

    def test_supported_finding_survives_later_failure_and_reaches_report(self):
        seed, uncertain = [f.observation.id for f in self.baseline.observations]
        steps = iter([self.inspect(), self.supported(self.clip)])

        def decide(role, context):
            if role == "investigation":
                return {"action": "delegate", "ids": [seed, uncertain], "reason": "Review both findings."}
            if role == "reporting":
                raise AssertionError("Execution failure must block additional model calls")
            if context["candidate_id"] == uncertain:
                raise VideoError("Later API failure")
            return {**anchored_verdict(next(steps), context["evidence"], seed), "reason": "Fixture."}

        with patch("security_augmented.workflow._load_archive", return_value=self.baseline.evidence):
            result = analyze_archive(VIDEO, ARCHIVES, decide=decide, budget=BUDGET, controller="langgraph")
        self.assertEqual(len(result.timeline), 1)
        self.assertEqual(len(result.unresolved), 1)
        self.assertEqual(result.completion["verification"], "partial")
        self.assertIn("1/2 checks completed", result.report)
        self.assertIn("An object was placed", result.report)
