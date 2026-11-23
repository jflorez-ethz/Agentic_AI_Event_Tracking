import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pytest

from security_augmented.workflow import Budget, analyze_archive

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "data/raw/LeftBag.mpg"
EXPERIMENTS = ROOT / "experiments"


class WorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = analyze_archive(
            VIDEO, (EXPERIMENTS / "e1_comparison_001", EXPERIMENTS / "e1_comparison_001_a_clip_retry_001"),
        )

    def test_video_starts_all_roles_without_question(self):
        result = self.analysis
        self.assertTrue(result.observations)
        self.assertEqual([event.category for event in result.timeline], ["object_placed"])
        placement, = result.timeline
        self.assertEqual(placement.verdict, "supported")
        self.assertEqual({c.modality for c in placement.citations}, {"frames", "clip"})
        self.assertTrue(all(c.frames and c.video_id == result.video.id for c in placement.citations))
        actions = {(e.actor, e.action) for e in result.trace}
        self.assertTrue({
            ("investigation", "propose"), ("verification", "inspect"),
            ("verification", "verdict"), ("reporting", "render"),
        }.issubset(actions))
        self.assertTrue(result.unresolved)
        self.assertIn("only", result.report.lower())
        self.assertIn(placement.citations[0].inspection_id, result.report)

    def test_queries_return_evidence_and_conserve_meaning(self):
        placement, = self.analysis.ask("Was an object left behind?").events
        self.assertEqual(placement.category, "object_placed")
        self.assertTrue(self.analysis.ask("What happened between 00:30 and 00:45?").events)
        removal = self.analysis.ask("Did anyone retrieve the object afterward?")
        self.assertEqual(removal.events, ())
        self.assertIn("does not establish", removal.text)
        self.assertEqual(self.analysis.ask("Was the object abandoned or left unattended?").events, ())
        self.assertIn("cannot establish", self.analysis.ask("Was it abandoned?").text)

    def test_reinspection_budget_is_enforced(self):
        with patch("security_augmented.workflow._load_archive", return_value=self.analysis.evidence):
            limited = analyze_archive(VIDEO, (), budget=Budget(max_inspections=0))
        self.assertEqual(limited.timeline, ())
        self.assertTrue(any(e.action == "budget_exhausted" for e in limited.trace))
        self.assertIn("insufficient", limited.report)

    def test_new_video_uses_bounded_injected_provider_without_question(self):
        from unittest.mock import Mock

        from security_augmented.observation import InferenceMetadata, ObservationResult
        from security_augmented.workflow import analyze_video

        provider = Mock()
        provider.infer.return_value = ObservationResult(
            InferenceMetadata("offline", "fixture", None, "1", "1"), (),
        )
        result = analyze_video(VIDEO, provider, budget=Budget(max_initial_windows=1))
        provider.infer.assert_called_once()
        request, = provider.infer.call_args.args
        self.assertEqual(request.media.inspection.requested_interval.end_us, 10_000_000)
        self.assertEqual(result.timeline, ())
        self.assertIn("No supported events", result.report)

    def test_time_query_can_attach_targeted_source_frames(self):
        answer = self.analysis.ask("What happened between 00:44 and 00:45?", inspect_missing=True)
        self.assertEqual(answer.events, ())
        self.assertIsNotNone(answer.inspection)
        self.assertTrue(answer.inspection.frames)
        self.assertLessEqual(len(answer.inspection.frames), 3)

    def test_invalid_controller_or_unavailable_graph_cannot_trigger_perception(self):
        from unittest.mock import Mock

        from security_augmented.contracts import VideoError
        from security_augmented.workflow import analyze_video

        provider = Mock()
        with self.assertRaises(VideoError):
            analyze_video(VIDEO, provider, controller="langgraph")
        with patch("security_augmented.graph_workflow.require_graph", side_effect=VideoError("missing graph")):
            with self.assertRaisesRegex(VideoError, "missing graph"):
                analyze_video(VIDEO, provider, controller="langgraph", decide=Mock())
        provider.infer.assert_not_called()


def test_saved_questions_use_source_identity_and_preserve_citations(capsys):
    from security_augmented.workflow import main

    saved = Path("experiments/meet_walk_split_500ms.bqVoWC/run/analysis.json")
    source = Path("data/raw/Meet_WalkSplit_pts.mp4")
    args = ["--saved-analysis", str(saved), "--question", "What happened between 10 and 15 seconds?"]
    assert main([str(source), *args]) == 0
    answer, = json.loads(capsys.readouterr().out)
    expected, = [e for e in json.loads(saved.read_text())["analysis"]["timeline"]
                 if e["interval"]["start_us"] == 10_000_000]
    assert answer["events"][0]["citations"] == expected["citations"]
    with pytest.raises(SystemExit):
        main(["data/raw/Meet_WalkTogether1_pts.mp4", *args])
    assert "does not match" in capsys.readouterr().err
