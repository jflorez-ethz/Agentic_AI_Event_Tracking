"""Opt-in live SDK smoke test using a synthetic image only."""

import hashlib
import os
import unittest

from security_augmented.contracts import FrameEvidence, Inspection, Interval
from security_augmented.gemini import GeminiAdapter
from security_augmented.observation import FrameSequenceInput, ObservationRequest


@unittest.skipUnless(os.getenv("E1_RUN_LIVE_SMOKE") == "1", "Live Gemini smoke test is opt-in")
class GeminiLiveSmokeTests(unittest.TestCase):
    def test_synthetic_image_structured_response(self):
        pixels = b"\xff\x00\x00" * (64 * 64)
        frame = FrameEvidence("synthetic-frame", 0, 0, 0, hashlib.sha256(pixels).hexdigest())
        inspection = Inspection(
            "synthetic-inspection", "synthetic-source", Interval(0, 1), (0,),
            "frames", "synthetic", "rgb24", "fixture", (frame,), (frame.id,), "complete",
            frame_size=(64, 64),
        )
        request = ObservationRequest(
            FrameSequenceInput(inspection, 64, 64, (pixels,)), ("visible_color",),
            "Describe the dominant visible color using category visible_color and cite F1.",
        )
        result = GeminiAdapter.from_env(authorized=True).infer(request)
        self.assertTrue(result.observations)
        self.assertEqual(result.observations[0].evidence.frame_ids, (frame.id,))
