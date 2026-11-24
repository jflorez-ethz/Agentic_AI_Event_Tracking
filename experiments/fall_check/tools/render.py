"""Contact sheet for posture labelling: frames every STEP s over [t0, t1], XML person boxes with their IDs.

    .venv/bin/python experiments/fall_check/tools/render.py VIDEO XML t0 t1 OUT.png [--step 0.25] [--crop x0,y0,x1,y1]
Times are PTS seconds of the analysed file. Identity and position come from the CAVIAR XML (production reader);
only posture is labelled by eye.
"""
import argparse
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from security_augmented.annotations import parse_annotations
from security_augmented.video import ingest

ROOT = Path(__file__).resolve().parents[3]


def frames_at(video, times):
    v = ingest(ROOT / "data/raw" / video)
    tb = v.time_base_num / v.time_base_den
    pts = [(p - v.first_display_pts) * tb for p in v.frame_pts]
    return [next(i for i, p in enumerate(pts) if p >= t - 1e-6) for t in times], pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("xml"); ap.add_argument("t0", type=float); ap.add_argument("t1", type=float)
    ap.add_argument("out"); ap.add_argument("--step", type=float, default=0.25); ap.add_argument("--crop", default="0,0,384,288")
    ap.add_argument("--scale", type=int, default=2); ap.add_argument("--cols", type=int, default=8)
    a = ap.parse_args()
    times = list(np.arange(a.t0, a.t1 + 1e-6, a.step))
    idx, pts = frames_at(a.video, times)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(ROOT / "data/raw" / a.video), "-fps_mode", "passthrough",
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stderr=subprocess.DEVNULL)
    F = np.frombuffer(raw, np.uint8).reshape(-1, 288, 384, 3)
    boxes = {f.number: [(o.id, o.box) for o in f.objects] for f in parse_annotations(ROOT / "data/annotations" / a.xml).frames}
    x0, y0, x1, y1 = map(int, a.crop.split(",")); s = a.scale
    w, h = (x1 - x0) * s, (y1 - y0) * s
    sheet = Image.new("RGB", (w * a.cols, h * ((len(idx) + a.cols - 1) // a.cols)))
    for k, n in enumerate(idx):
        im = Image.fromarray(F[n]).crop((x0, y0, x1, y1)).resize((w, h), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        for oid, b in boxes.get(n, []):
            r = [(b.xc - b.width / 2 - x0) * s, (b.yc - b.height / 2 - y0) * s, (b.xc + b.width / 2 - x0) * s, (b.yc + b.height / 2 - y0) * s]
            d.rectangle(r, outline=(0, 255, 0)); d.text((r[0] + 2, r[1] + 1), oid, fill=(0, 255, 0))
        d.text((3, 3), f"{pts[n]:.2f}s #{n}", fill=(255, 255, 0))
        sheet.paste(im, ((k % a.cols) * w, (k // a.cols) * h))
    sheet.save(a.out)


if __name__ == "__main__":
    main()
