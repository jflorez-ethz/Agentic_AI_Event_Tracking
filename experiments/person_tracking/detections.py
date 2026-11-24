"""Cache RF-DETR Nano person detections with confidences (threshold 0.1) for the nine annotated CAVIAR clips.

Local, CPU, no network after the cached weights. Every `stride`-th frame, in display order with PTS passthrough.

    .venv/bin/python experiments/person_tracking/detections.py --stride 5
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW, ANNOTATIONS = ROOT / "data/raw", ROOT / "data/annotations"
VIDEOS = [  # name, decoded source, CAVIAR XML, role in the protocol
    ("Walk2", "Walk2.mpg", "wk2gt.xml", "tuning"),
    ("LeftBag", "LeftBag.mpg", "LeftBag.xml", "tuning"),
    ("LeftBag_PickedUp", "LeftBag_PickedUp.mpg", "lbpugt.xml", "test"),
    ("LeftBag_AtChair", "LeftBag_AtChair.mpg", "LeftBag_AtChair.xml", "test"),
    ("LeftBox", "LeftBox_pts.mkv", "LeftBox.xml", "test"),
    ("Rest_FallOnFloor", "Rest_FallOnFloor.mpg", "Rest_FallOnFloor.xml", "test"),
    ("TwoEnterShop1front", "TwoEnterShop1front_pts.mkv", "f2es1gt.xml", "test"),
    ("Meet_WalkSplit", "Meet_WalkSplit_pts.mp4", "mws1gt.xml", "test"),
    ("Meet_WalkTogether1", "Meet_WalkTogether1_pts.mp4", "Meet_WalkTogether1.xml", "test"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stride", type=int, default=5)
    args = parser.parse_args()
    from PIL import Image
    from rfdetr import RFDETRNano

    model = RFDETRNano()
    out = Path(__file__).with_name(f"detections_stride{args.stride}.json")
    cache = json.loads(out.read_text()) if out.exists() else {}
    for name, video, _, _ in VIDEOS:
        if name in cache:
            continue
        path = str(RAW / video)
        w, h = map(int, re.findall(r"\d+", subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True).stdout)[:2])
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough", "-f", "rawvideo",
                                 "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        rows, n = {}, 0
        while (chunk := proc.stdout.read(w * h * 3)) and len(chunk) == w * h * 3:
            if n % args.stride == 0:
                d = model.predict(Image.fromarray(np.frombuffer(chunk, np.uint8).reshape(h, w, 3)), threshold=0.1)
                rows[n] = [[*map(float, b), float(c)] for b, c, k in zip(d.xyxy, d.confidence, d.data["class_name"]) if k == "person"]
            n += 1
        proc.wait()
        cache[name] = rows
        out.write_text(json.dumps(cache))
        print(name, n, "frames", sum(map(len, rows.values())), "detections", flush=True)


if __name__ == "__main__":
    main()
