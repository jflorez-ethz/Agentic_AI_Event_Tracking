from dataclasses import replace
from fractions import Fraction
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from security_augmented.annotations import align_leftbag, parse_annotations
from security_augmented.contracts import Interval, VideoError
from security_augmented.video import extract_clip, ingest, validate_clip

ROOT = Path(__file__).resolve().parents[1]


class FoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.video = ingest(ROOT / "data/raw/LeftBag.mpg")

    def test_leftbag_annotations_map_in_display_order(self):
        dataset = parse_annotations(ROOT / "data/annotations/LeftBag.xml")
        self.assertEqual(tuple(f.number for f in dataset.frames), tuple(range(1439)))
        first = dataset.frames[0].objects[0]
        self.assertEqual((first.id, first.box.xc, first.box.yc), ("0", 184, 204))
        self.assertEqual(dataset.frames[0].groups[0].members, ("1", "2"))
        aligned = align_leftbag(dataset, self.video)
        self.assertEqual((aligned[0].display_index, aligned[0].source_pts), (0, 0))
        self.assertEqual(aligned[1].source_time, Fraction(2797, 10000))
        self.assertEqual([a.source_pts for a in aligned[80:82]], [313173, 313173])
        self.assertEqual(aligned[-1].source_pts, 5198373)
        self.assertEqual(len(self.video.frame_pts) - len(aligned), 1)
        with self.assertRaises(VideoError):
            align_leftbag(replace(dataset, sha256="other"), self.video)

    def test_parser_rejects_invalid_indices(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotation.xml"
            for indices in [(0, 0), (0, 2), (0, -1), ("bad",), ()]:
                frames = "".join(f'<frame number="{i}"/>' for i in indices)
                path.write_text(f'<dataset name="test">{frames}</dataset>')
                with self.subTest(indices=indices), self.assertRaises(VideoError):
                    parse_annotations(path)

    def test_clip_replays_duplicate_pts_and_records_bounds(self):
        requested = Interval(3_390_000, 3_520_000)
        clip, data = extract_clip(self.video, requested)
        self.assertEqual(clip.requested_interval, requested)
        self.assertEqual(clip.actual_source_interval, Interval(3_399_700, 3_559_700))
        self.assertEqual([f.source.display_index for f in clip.frames], [79, 80, 81, 82])
        self.assertEqual([f.source.pts for f in clip.frames], [305973, 313173, 313173, 316773])
        self.assertEqual([f.clip_pts for f in clip.frames], [0, 80, 80, 120])
        self.assertEqual(clip.clip_duration_us, 160_000)
        validate_clip(self.video, clip, data)
        self.assertEqual((clip, data), extract_clip(self.video, requested))
        for record, payload in [
            (clip, data[:-1]),
            (replace(clip, actual_source_interval=requested), data),
            (replace(clip, frames=clip.frames[:-1]), data),
        ]:
            with self.assertRaises(VideoError):
                validate_clip(self.video, record, payload)

    def test_clip_boundaries_and_empty_window(self):
        clip, _ = extract_clip(self.video, Interval(0, 1))
        self.assertEqual(clip.actual_source_interval, Interval(0, 40_000))
        last = self.video.duration_us
        clip, data = extract_clip(self.video, Interval(last - 40_000, last))
        self.assertEqual(clip.actual_source_interval.end_us, last)
        validate_clip(self.video, clip, data)
        for interval in [Interval(1, 279700), Interval(-1, 1), Interval(last - 1, last + 1)]:
            with self.assertRaises(VideoError):
                extract_clip(self.video, interval)

    def test_clip_round_trip_with_nonzero_start_and_vfr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vfr.mkv"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=32x32:rate=25", "-frames:v", "3",
                "-vf", "setpts=N*N+25", "-fps_mode", "passthrough", "-c:v", "ffv1",
                str(path),
            ], check=True)
            video = ingest(path)
            clip, data = extract_clip(video, Interval(39_999, 200_000))
            self.assertEqual(clip.actual_source_interval, Interval(40_000, 200_000))
            self.assertEqual([f.source.pts for f in clip.frames], [1040, 1160])
            self.assertEqual([f.clip_pts for f in clip.frames], [0, 120])
            validate_clip(video, clip, data)

    def test_clip_records_container_rounding_separately_from_source(self):
        clip, data = extract_clip(self.video, Interval(0, 300_000))
        self.assertEqual([frame.source.source_time_us for frame in clip.frames], [0, 279_700])
        self.assertEqual([frame.clip_pts for frame in clip.frames], [0, 280])
        self.assertEqual(clip.clip_time_base, Fraction(1, 1000))
        self.assertEqual(clip.actual_source_interval, Interval(0, 319_700))
        self.assertEqual(clip.clip_duration_us, 320_000)
        validate_clip(self.video, clip, data)

    def test_clip_preserves_longer_terminal_frame_in_vfr_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vfr.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=32x32:rate=25", "-frames:v", "3",
                "-vf", "setpts=N*N+25", "-fps_mode", "passthrough",
                "-c:v", "mpeg4", "-bf", "0", str(path),
            ], check=True)
            video = ingest(path)
            clip, data = extract_clip(video, Interval(40_000, 100_000))
            self.assertEqual(clip.actual_source_interval, Interval(40_000, 160_000))
            self.assertEqual(clip.clip_duration_us, 120_000)
            self.assertEqual(clip.clip_last_frame_duration_pts, 120)
            validate_clip(video, clip, data)

    def test_clip_verification_checks_format_and_pixels_after_digest_match(self):
        clip, data = extract_clip(self.video, Interval(0, 320_000))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.mkv"
            path.write_bytes(data)
            for codec, filter_ in [("huffyuv", "null"), ("ffv1", "negate")]:
                other = Path(directory) / f"{codec}.mkv"
                subprocess.run([
                    "ffmpeg", "-v", "error", "-i", str(path), "-vf", filter_,
                    "-c:v", codec, "-threads", "1", "-fps_mode", "passthrough", str(other),
                ], check=True)
                payload = other.read_bytes()
                forged = replace(clip, artifact_sha256=hashlib.sha256(payload).hexdigest())
                with self.subTest(codec=codec), self.assertRaisesRegex(
                    VideoError, "format" if codec == "huffyuv" else "pixels",
                ):
                    validate_clip(self.video, forged, payload)
