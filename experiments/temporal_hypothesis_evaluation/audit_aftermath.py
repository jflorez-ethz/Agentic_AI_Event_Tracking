"""Verify archived A/B inputs and rerender only the additional frames locally."""
import argparse
import hashlib
import json
from pathlib import Path

from paired import SOURCE, assess_aftermath, ingest, load_context
from security_augmented.video import _decode, _run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contact-sheet", type=Path, required=True)
    args = parser.parse_args()
    path = Path(__file__).parent / "paired.jqmQZe/run"
    video = ingest(SOURCE)
    focus, _ = load_context(video)

    def read(arm, name):
        return json.loads((path / arm / f"{name}.json").read_text())

    arms = {arm: read(arm, "supplied-frames")["frames"] for arm in "AB"}
    assert arms["B"][:len(arms["A"])] == arms["A"]
    frames = arms["B"]
    indices = tuple(f["display_index"] for f in frames)
    pixels = _decode(video, indices)
    for f, rgb in zip(frames, pixels, strict=True):
        pts = video.frame_pts[f["display_index"]]
        assert pts == f["pts"] and int(video.time_at_pts(pts) * 1_000_000) == f["source_time_us"]
        assert hashlib.sha256(rgb).hexdigest() == f["rgb24_sha256"]
    _run("ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
         "-video_size", f"{video.width}x{video.height}", "-i", "pipe:0",
         "-vf", "tile=5x2", "-frames:v", "1", "-threads", "1", str(args.contact_sheet),
         input_bytes=b"".join(pixels[len(arms["A"]):]))
    for arm, supplied in arms.items():
        perception = read(arm, "perception")
        assert all(set(o["evidence"]["frame_ids"]) <= {f["id"] for f in supplied}
                   for o in perception["observations"])
        selection = read(arm, "selection")
        role_calls = selection["role_calls"] + read(arm, "execution-cost")["role_calls"]
        tokens = sum(c["usage"]["total_token_count"] for c in role_calls)
        total = tokens + dict(perception["metadata"]["usage"])["total_token_count"]
        verdict = assess_aftermath(read(arm, "verification-decision"), focus, [])
        print(arm, len(supplied), [f["source_time_us"] for f in supplied], total, verdict)
    print("Common frames verified:", len(arms["A"]))


if __name__ == "__main__":
    main()
