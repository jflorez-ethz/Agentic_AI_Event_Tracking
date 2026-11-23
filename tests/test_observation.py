from dataclasses import replace
from pathlib import Path
import unittest

from security_augmented.contracts import Interval, VideoError
from security_augmented.observation import (
    ClipInput, ClipReference, FrameReference, FrameSequenceInput, InferenceMetadata,
    Observation, ObservationRequest, ObservationResult, resolve_clip_reference,
    validate_request, validate_result,
)
from security_augmented.video import extract_clip, ingest, sample, validate_reference

ROOT = Path(__file__).resolve().parents[1]


class ObservationContractTests(unittest.TestCase):
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
        cls.metadata = InferenceMetadata("local-test", "fixture", "1", "1", "prompt-v1")

    def test_frame_observations_reference_only_submitted_frames(self):
        request = ObservationRequest(self.frames, ("object_placed",), "Describe the scene.")
        validate_request(request)
        inspection = self.frames.inspection
        observation = Observation(
            "obs1", inspection.id, "object_placed", "A bag rests on the floor.",
            FrameReference((inspection.frames[0].id,)), "Sparse sampling.", "Timing uncertain.",
        )
        result = ObservationResult(self.metadata, (observation,))
        validate_result(request, result)
        for invalid in [
            replace(observation, evidence=FrameReference(("fabricated",))),
            replace(observation, evidence=FrameReference(())),
            replace(observation, category="unlisted"),
            replace(observation, inspection_id="other"),
            replace(observation, uncertainty=""),
        ]:
            with self.assertRaises(VideoError):
                validate_result(request, replace(result, observations=(invalid,)))
        with self.assertRaises(VideoError):
            validate_request(replace(request, media=replace(self.frames, rgb24_frames=(b"bad",) * 2)))

    def test_frame_input_rejects_incorrect_image_dimensions(self):
        request = ObservationRequest(
            replace(self.frames, width=self.frames.height, height=self.frames.width),
            ("object_placed",), "Describe the scene.",
        )
        with self.assertRaises(VideoError):
            validate_request(request)

    def test_clip_reference_uses_clip_clock_and_resolves_to_source(self):
        request = ObservationRequest(self.clip, ("object_placed",), "Describe the scene.")
        inspection = self.clip.inspection
        reference = ClipReference(Interval(280_000, 281_000))
        observation = Observation(
            "obs2", inspection.id, "object_placed", "A bag rests on the floor.",
            reference, "Overhead view.", "Contents unknown.",
        )
        result = ObservationResult(self.metadata, (observation,))
        validate_result(request, result)
        self.assertEqual(resolve_clip_reference(inspection, reference), (inspection.frames[1].source,))
        previous = ClipReference(Interval(279_700, 280_000))
        self.assertEqual(resolve_clip_reference(inspection, previous), (inspection.frames[0].source,))
        for invalid in [ClipReference(Interval(319_999, 320_001)), FrameReference(("frame",))]:
            with self.assertRaises(VideoError):
                validate_result(request, replace(result, observations=(replace(observation, evidence=invalid),)))
        with self.assertRaises(VideoError):
            validate_request(replace(request, media=replace(self.clip, artifact=b"wrong")))
