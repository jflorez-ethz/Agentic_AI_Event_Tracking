"""RF-DETR Nano person detections at stride 5 for chosen clips and inference shape, with per-clip CPU timing.

    .venv/bin/python experiments/person_tracking/nano_x3/detect.py --shape 864x1152 --out det_x3.json Walk2 LeftBag
"""
import argparse, json, re, subprocess, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / "data/raw"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("clips", nargs="+")
    a = ap.parse_args()
    import rfdetr
    from PIL import Image
    shape = tuple(map(int, a.shape.split("x")))
    model = rfdetr.RFDETRNano()
    out = HERE / a.out
    cache = json.loads(out.read_text()) if out.exists() else {}
    for name in a.clips:
        if name in cache:
            continue
        path = str(RAW / f"{name}.mpg")
        w, h = map(int, re.findall(r"\d+", subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=width,height", "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout)[:2])
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough", "-f", "rawvideo",
                                 "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        rows, n, seconds = {}, 0, 0.0
        while (chunk := proc.stdout.read(w * h * 3)) and len(chunk) == w * h * 3:
            if n % a.stride == 0:
                image = Image.fromarray(np.frombuffer(chunk, np.uint8).reshape(h, w, 3))
                t0 = time.monotonic()
                d = model.predict(image, threshold=0.1, shape=shape)
                rows[n] = [[*map(float, b), float(c)] for b, c, k in zip(d.xyxy, d.confidence, d.data["class_name"]) if k == "person"]
                seconds += time.monotonic() - t0
            n += 1
        proc.wait()
        cache[name] = rows
        cache.setdefault("_cpu", {})[name] = {"seconds": round(seconds, 1), "video_s": round(n / 25, 1)}
        out.write_text(json.dumps(cache))
        print(name, a.shape, n, "frames", f"{seconds / (n / 25) * 60:.0f} s CPU per video minute", flush=True)


if __name__ == "__main__":
    main()
