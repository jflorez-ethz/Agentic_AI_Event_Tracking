from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from security_augmented.contracts import Interval, VideoError
from security_augmented.video import ingest, sample, validate_reference, validate_source


ROOT = Path(__file__).resolve().parents[1]
LEFTBAG = ROOT / "data/raw/LeftBag.mpg"


class LeftBagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.video = ingest(LEFTBAG)

    def test_ingestion_preserves_actual_frame_timing(self):
        video = self.video
        self.assertEqual(video.sha256, hashlib.sha256(LEFTBAG.read_bytes()).hexdigest())
        self.assertEqual((video.stream_index, video.first_display_pts), (0, 0))
        self.assertEqual((video.time_base_num, video.time_base_den), (1, 90000))
        self.assertEqual(video.duration_us, 57_839_700)
        self.assertEqual(len(video.frame_pts), 1440)
        self.assertEqual(video.frame_pts[:2], (0, 25173))

    def test_sample_and_replay_beginning_boundary_middle_and_end(self):
        interval = Interval(0, self.video.duration_us)
        requests = [0, 1, 8_000_000, 28_000_000, 57_790_000, 57_839_699]
        inspection = sample(self.video, interval, requests)
        self.assertEqual(inspection, sample(self.video, interval, requests))
        self.assertEqual(inspection.status, "partial")
        self.assertEqual(inspection.requested_times_us, tuple(requests))
        self.assertIsNone(inspection.frame_ids_by_request[-1])
        self.assertEqual(len(inspection.frames), 5)
        self.assertEqual(inspection.frames[1].pts, 25173)
        self.assertEqual(inspection.frames[1].source_time_us, 279700)
        for frame in inspection.frames:
            pixels = validate_reference(self.video, inspection, frame.id)
            self.assertEqual(len(pixels), 384 * 288 * 3)
            self.assertEqual(hashlib.sha256(pixels).hexdigest(), frame.rgb24_sha256)
        self.assertEqual(json.loads(json.dumps(asdict(inspection)))["schema_version"], 1)

    def test_half_open_bounds_and_duplicate_hits(self):
        empty = sample(self.video, Interval(1, 279700), [1])
        self.assertEqual(empty.status, "empty")
        self.assertEqual(empty.frames, ())
        inspection = sample(self.video, Interval(1, 279701), [279700, 1])
        self.assertEqual(inspection.status, "complete")
        self.assertEqual(len(inspection.frames), 1)
        self.assertEqual(inspection.frame_ids_by_request, (inspection.frames[0].id,) * 2)
        for interval, requests in [
            (Interval(-1, 1), [0]), (Interval(1, 1), [1]),
            (Interval(0, self.video.duration_us + 1), [0]),
            (Interval(0, 1), [1]), (Interval(0, 1), [False]), (Interval(0, 1), []),
        ]:
            with self.subTest(interval=interval, requests=requests):
                with self.assertRaises(VideoError):
                    sample(self.video, interval, requests)

    def test_equal_pts_choose_first_frame_in_display_order(self):
        self.assertEqual(self.video.frame_pts[80:82], (313173, 313173))
        inspection = sample(self.video, Interval(3_479_700, 3_479_701), [3_479_700])
        frame, = inspection.frames
        self.assertEqual((frame.display_index, frame.pts), (80, 313173))
        validate_reference(self.video, inspection, frame.id)

    def test_reference_rejects_a_forged_source_clock(self):
        forged = replace(self.video, first_display_pts=1)
        inspection = sample(forged, Interval(0, 300_000), [0])
        with self.assertRaises(VideoError):
            validate_reference(forged, inspection, inspection.frames[0].id)

    def test_rejects_invalid_references_and_changed_source(self):
        inspection = sample(self.video, Interval(0, 1), [0])
        frame = inspection.frames[0]
        for invalid, frame_id in [
            (inspection, "unknown"),
            (replace(inspection, video_id="another-video"), frame.id),
            (replace(inspection, frame_ids_by_request=(None,)), frame.id),
            (replace(inspection, requested_interval=Interval(1, 2)), frame.id),
            (replace(inspection, frames=(replace(frame, rgb24_sha256="wrong"),)), frame.id),
            (replace(inspection, frames=(replace(frame, pts=1),)), frame.id),
        ]:
            with self.subTest(invalid=invalid, frame_id=frame_id):
                with self.assertRaises(VideoError):
                    validate_reference(self.video, invalid, frame_id)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copy.mpg"
            shutil.copyfile(LEFTBAG, path)
            relocated = replace(self.video, source_path=str(path))
            validate_source(relocated)
            with path.open("ab") as source:
                source.write(b"changed")
            with self.assertRaises(VideoError):
                validate_reference(relocated, inspection, frame.id)
            path.unlink()
            with self.assertRaises(VideoError):
                validate_source(relocated)
            path.write_bytes(b"invalid media")
            with self.assertRaises(VideoError):
                ingest(path)


class VariableRateTests(unittest.TestCase):
    def test_nonzero_start_and_variable_rate_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vfr.mkv"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=32x32:rate=25", "-frames:v", "3",
                "-vf", "setpts=N*N+25", "-fps_mode", "passthrough", "-c:v", "ffv1",
                str(path),
            ], check=True)
            video = ingest(path)
            self.assertEqual(video.frame_pts, (1000, 1040, 1160))
            self.assertEqual(video.duration_us, 200_000)
            inspection = sample(video, Interval(0, 200_000), [0, 40_001, 160_000])
            self.assertEqual([frame.pts for frame in inspection.frames], [1000, 1160])
            for frame in inspection.frames:
                self.assertEqual(video.time_at_pts(frame.pts),
                                 Fraction(frame.source_time_us, 1_000_000))
                validate_reference(video, inspection, frame.id)
