"""Build model-blind continuity packets and verify their source frames."""
import hashlib
import json
from pathlib import Path

from security_augmented.video import _decode, _run, ingest

ROOT = Path(__file__).resolve().parent
SOURCE = Path("data/raw/Meet_WalkSplit_pts.mp4")
# Coordinates identify local image regions, with origin at the top left.
CASES = {
    "K7": ((250, 300, 325), (105, 120), (78, 100)),
    "M2": ((250, 251, 325), (105, 120), (78, 100)),
    "Q4": ((250, 300, 325), (105, 120), (66, 145)),
}

video = ingest(SOURCE)
probe = json.loads(_run("ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "frame=pts", "-of", "json", str(SOURCE)).stdout)
assert tuple(int(f["pts"]) for f in probe["frames"]) == video.frame_pts
indices = tuple(sorted({i for frames, _, _ in CASES.values() for i in frames} | {363}))
decoded = dict(zip(indices, _decode(video, indices), strict=True))
manifest = {"source": str(SOURCE), "sha256": video.sha256, "time_base": str(video.time_base), "cases": {}}
for label, (frames, start, finish) in CASES.items():
    directory = ROOT / "packets" / label
    directory.mkdir(parents=True, exist_ok=True)
    refs = []
    for index in frames:
        rgb = decoded[index]
        name = f"{index:04d}.png"
        size = f"{video.width}x{video.height}"
        png = _run("ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
                   "-video_size", size, "-i", "pipe:0", "-frames:v", "1", "-threads", "1",
                   "-c:v", "png", "-f", "image2pipe", "pipe:1", input_bytes=rgb).stdout
        (directory / name).write_bytes(png)
        restored = _run("ffmpeg", "-v", "error", "-i", str(directory / name),
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "pipe:1").stdout
        assert restored == rgb
        pts = video.frame_pts[index]
        refs.append({"file": name, "index": index, "pts": pts,
                     "source_time_us": int(video.time_at_pts(pts) * 1_000_000),
                     "rgb24_sha256": hashlib.sha256(rgb).hexdigest()})
    packet = {"case": label, "frames": refs, "start_region_xy": start, "end_region_xy": finish}
    (directory / "input.json").write_text(json.dumps(packet, indent=2) + "\n")
    manifest["cases"][label] = packet
assert {tuple(case["frames"][i]["index"] for i in (0, -1)) for case in manifest["cases"].values()} == {(250, 325)}
assert all(len(case["frames"]) == 3 for case in manifest["cases"].values())
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Verified 3 three-frame packets and PNG pixel round trips; all horizons are 10–13 s.")
