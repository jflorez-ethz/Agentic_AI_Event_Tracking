import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from security_augmented.contracts import Interval, VideoError
from security_augmented.gemini import GeminiAdapter, GeminiFailure
from security_augmented.observation import ClipInput, FrameSequenceInput, ObservationRequest
from security_augmented.video import extract_clip, ingest, sample, validate_reference

ROOT = Path(__file__).resolve().parents[1]


class GeminiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        video = ingest(ROOT / "data/raw/LeftBag.mpg")
        interval = Interval(0, 300_000)
        inspection = sample(video, interval, [0, 1])
        cls.frames = FrameSequenceInput(
            inspection, video.width, video.height,
            tuple(validate_reference(video, inspection, frame.id) for frame in inspection.frames),
        )
        cls.clip = ClipInput(*extract_clip(video, interval))

    def setUp(self):
        self.client = Mock()
        self.adapter = GeminiAdapter(client=self.client)
        self.item = {
            "category": "object_placed", "description": "Synthetic response for contract testing.",
            "visibility_limits": "Overhead view.", "uncertainty": "Timing uncertain.",
            "frame_labels": ["F1"], "clip_interval_us": [],
        }

    def respond(self, text):
        self.client.models.generate_content.return_value = SimpleNamespace(
            text=text, model_version="fixture-version",
            usage_metadata=SimpleNamespace(prompt_token_count=320, candidates_token_count=80),
        )

    def request(self, media):
        return ObservationRequest(media, ("object_placed",), "Describe visible activity.")

    def test_frames_are_png_with_actual_timestamps_and_resolved_references(self):
        self.respond(json.dumps({"observations": [self.item]}))
        result = self.adapter.infer(self.request(self.frames))
        call = self.client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "gemini-3.6-flash")
        self.assertEqual(call["config"]["thinking_config"], {"thinking_level": "HIGH"})
        parts = call["contents"][0]["parts"]
        self.assertIn("279700", parts[3]["text"])
        self.assertEqual(parts[4]["inline_data"]["mime_type"], "image/png")
        self.assertTrue(parts[4]["inline_data"]["data"].startswith(b"\x89PNG"))
        self.assertEqual(call["config"]["response_mime_type"], "application/json")
        observation, = result.observations
        self.assertEqual(observation.source_video_id, self.frames.inspection.video_id)
        self.assertEqual(observation.evidence.frame_ids, (self.frames.inspection.frames[0].id,))
        self.assertEqual(observation.inference_metadata.model_version, "fixture-version")

    def test_clip_submits_verified_webm_with_explicit_fps_and_resolves_source(self):
        self.item.update(frame_labels=[], clip_interval_us=[280000, 281000])
        self.respond(json.dumps({"observations": [self.item]}))
        prepared = self.adapter.prepare(self.request(self.clip))
        self.assertEqual(prepared.media_map["frames"][1]["clip_pts"], 280)
        self.assertEqual(prepared.media_map["frames"][1]["source"]["source_time_us"], 279700)
        result = self.adapter.infer_prepared(prepared)
        media = self.client.models.generate_content.call_args.kwargs["contents"][0]["parts"][-1]
        self.assertEqual(media["inline_data"]["mime_type"], "video/webm")
        self.assertEqual(media["video_metadata"]["fps"], 2.0)
        self.assertEqual(result.observations[0].evidence.interval, Interval(280000, 281000))

    def test_invalid_response_retains_raw_text_and_usage(self):
        for patch_ in [{"frame_labels": ["missing"]}, {"clip_interval_us": [0, 1]}, {"category": "other"}]:
            raw = json.dumps({"observations": [{**self.item, **patch_}]})
            self.respond(raw)
            with self.assertRaises(GeminiFailure) as caught:
                self.adapter.infer(self.request(self.frames))
            self.assertEqual(caught.exception.raw_response, raw)
            self.assertEqual(dict(caught.exception.metadata.usage)["prompt_token_count"], 320)

    def test_client_requires_authorization_before_credentials(self):
        with self.assertRaisesRegex(VideoError, "authorization"):
            GeminiAdapter.from_env(authorized=False)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(VideoError, "API_KEY"):
                GeminiAdapter.from_env(authorized=True)

    def test_api_failure_keeps_latency_and_excludes_secret_from_error_message(self):
        self.client.models.generate_content.side_effect = RuntimeError("secret credential")
        with self.assertRaises(GeminiFailure) as caught:
            self.adapter.infer(self.request(self.frames))
        self.assertNotIn("secret", str(caught.exception))
        self.assertIsNotNone(caught.exception.metadata.elapsed_ms)

    def test_pilot_archives_exact_media_and_attempt_results(self):
        import hashlib
        import tempfile

        from security_augmented.e1 import run_pilot

        self.respond('{"observations":[]}')
        source = ROOT / "data/raw/LeftBag.mpg"
        with tempfile.TemporaryDirectory() as directory, patch(
            "security_augmented.e1.WINDOWS", (("sample", Interval(0, 300000)),),
        ):
            output = Path(directory) / "result"
            summary = run_pilot(self.adapter, source, output, repetitions=1)
            self.assertEqual(self.client.models.generate_content.call_count, 2)
            for mode in ("frames", "clip"):
                path = output / "sample" / mode
                manifest = json.loads((path / "request.json").read_text())
                blob = manifest["contents"][0]["parts"][-1]["inline_data"]
                self.assertEqual(hashlib.sha256((path / blob["path"]).read_bytes()).hexdigest(), blob["sha256"])
                attempt = json.loads((path / "attempt-1.json").read_text())
                self.assertEqual(attempt["status"], "success")
                self.assertEqual(attempt["raw_response"], '{"observations":[]}')
                self.assertIsNone(summary["windows"]["sample"][mode]["provider_processed_video_frames"])
