import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from security_augmented.e1 import _load_clip_retry, run_clip_retry
from security_augmented.gemini import GeminiAdapter
from security_augmented.contracts import VideoError


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "experiments/e1_comparison_001/window-a/clip"
SOURCE = ROOT / "data/raw/LeftBag.mpg"


class ClipRetryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.prepared = _load_clip_retry(ARCHIVE, SOURCE)

    def test_replay_exact_request_once_and_empty_is_miss(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(text='{"observations":[]}')
        adapter = GeminiAdapter(client=client, model=self.model)
        with TemporaryDirectory() as temp:
            output = Path(temp) / "retry"
            summary = run_clip_retry(adapter, self.prepared, output, live=True)
            attempt = json.loads((output / "attempt-1.json").read_text())
            self.assertEqual(attempt["status"], "success")
            self.assertEqual(attempt["placement_assessment"], "missed_positive")
            self.assertEqual(summary["attempts"], ["success"])
            self.assertEqual((output / "part-1.webm").read_bytes(), (ARCHIVE / "part-1.webm").read_bytes())
            self.assertEqual(json.loads((output / "request.json").read_text()), json.loads((ARCHIVE / "request.json").read_text()))
            with self.assertRaises(FileExistsError):
                run_clip_retry(adapter, self.prepared, output, live=True)
            client.models.generate_content.assert_called_once_with(
                model=self.model, contents=self.prepared.contents,
                config={**self.prepared.config, "automatic_continuation": False},
            )

    def test_validation_and_api_failure_are_distinct_and_do_not_retry(self):
        client = Mock()
        adapter = GeminiAdapter(client=client, model=self.model)
        for name, api_error in (("api", RuntimeError("offline failure")), ("output", None)):
            with self.subTest(name=name), TemporaryDirectory() as temp:
                client.reset_mock()
                client.models.generate_content.side_effect = api_error
                client.models.generate_content.return_value = SimpleNamespace(text='invalid JSON')
                output = Path(temp) / "retry"
                run_clip_retry(adapter, self.prepared, output, live=True)
                attempt = json.loads((output / "attempt-1.json").read_text())
                self.assertEqual(attempt["failure_stage"], "api" if api_error else "validation")
                client.models.generate_content.assert_called_once()

    def test_bad_payload_hash_is_rejected_before_ingest(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in ("request.json", "attempt-1.json"):
                (directory / name).write_bytes((ARCHIVE / name).read_bytes())
            (directory / "part-1.webm").write_bytes(b"truncated")
            with patch("security_augmented.e1.ingest") as ingest:
                with self.assertRaisesRegex(VideoError, "hash or size"):
                    _load_clip_retry(directory, SOURCE)
                ingest.assert_not_called()

    def test_dry_run_does_not_use_client(self):
        client = Mock()
        with TemporaryDirectory() as temp:
            output = Path(temp) / "retry"
            summary = run_clip_retry(GeminiAdapter(client=client, model=self.model), self.prepared, output)
            self.assertEqual(summary["status"], "prepared_offline")
            self.assertFalse(list(output.glob("attempt-*")))
            client.models.generate_content.assert_not_called()

    def test_placement_claim_resolves_or_fails_without_an_extra_attempt(self):
        item = {
            "category": "object_placed", "description": "A person sets down a bag.",
            "visibility_limits": "Overhead view.", "uncertainty": "Release timing unclear.",
            "frame_labels": [], "clip_interval_us": [1_000_000, 2_000_000],
        }
        for bounds, finish, expected in [
            ([1_000_000, 2_000_000], "STOP", "success"),
            ([1_000_000, 4_000_001], "STOP", "failed"),
            ([1_000_000, 2_000_000], "MAX_TOKENS", "failed"),
        ]:
            with self.subTest(bounds=bounds, finish=finish), TemporaryDirectory() as temp:
                client = Mock()
                client.models.generate_content.return_value = SimpleNamespace(
                    text=json.dumps({"observations": [{**item, "clip_interval_us": bounds}]}),
                    candidates=[SimpleNamespace(finish_reason=finish)],
                    usage_metadata=SimpleNamespace(prompt_token_count=400, candidates_token_count=70),
                )
                output = Path(temp) / "retry"
                run_clip_retry(GeminiAdapter(client=client, model=self.model), self.prepared, output, live=True)
                attempt = json.loads((output / "attempt-1.json").read_text())
                self.assertEqual(attempt["status"], expected)
                self.assertEqual(dict(attempt["metadata"]["usage"])["prompt_token_count"], 400)
                self.assertGreaterEqual(attempt["metadata"]["elapsed_ms"], 0)
                if expected == "success":
                    self.assertEqual(attempt["placement_assessment"], "placement_reported_review_required")
                    self.assertTrue(attempt["replay"][0]["resolved_source_frames"])
                else:
                    self.assertEqual(attempt["failure_stage"], "validation")
                    self.assertEqual(attempt["placement_assessment"], "unscored")
                client.models.generate_content.assert_called_once()

    def test_installed_sdk_sends_same_wire_payload_and_stops_on_continuation(self):
        try:
            import httpx2 as httpx
        except ImportError:
            import httpx
        from google import genai
        from google.genai import types

        if "automatic_continuation" not in types.GenerateContentConfig.model_fields:
            self.skipTest("Installed SDK does not expose automatic continuation")
        bodies = []

        def respond(request):
            bodies.append(request.content)
            response = {
                "candidates": [{"finishReason": "CONTINUATION", "content": {
                    "parts": [{"text": '{"observations":[]}'}],
                }}],
                "continuationToken": "dG9rZW4=",
            }
            return httpx.Response(200, json=response)

        with TemporaryDirectory() as temp, httpx.Client(
            transport=httpx.MockTransport(respond),
        ) as transport:
            options = types.HttpOptions(
                api_version="v1beta", httpx_client=transport,
                retry_options=types.HttpRetryOptions(attempts=1),
            )
            with genai.Client(api_key="offline-test", vertexai=False, http_options=options) as client:
                adapter = GeminiAdapter(client=client, model=self.model)
                output = Path(temp) / "retry"
                run_clip_retry(adapter, self.prepared, output, live=True)
                self.assertEqual(len(bodies), 1)
                self.assertNotIn(b"automaticContinuation", bodies[0])
                self.assertNotIn(b"automatic_continuation", bodies[0])
                attempt = json.loads((output / "attempt-1.json").read_text())
                self.assertEqual(attempt["failure_stage"], "validation")
