"""Cache RF-DETR Nano person boxes at 5 fps (the realistic person filter). Local, CPU, no network after weights.

    .venv/bin/python experiments/stationary_objects/persons.py
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from videos import RAW, VIDEOS

OUT = Path(__file__).with_name("persons_rfdetr_stride5.json")


def main():
    from PIL import Image
    from rfdetr import RFDETRNano

    model = RFDETRNano()
    cache = {}
    for name, video, _ in VIDEOS:
        path = str(RAW / video)
        width, height = map(int, re.findall(r"\d+", subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True).stdout)[:2])
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough", "-f", "rawvideo",
                                 "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE)
        boxes, n, size = {}, 0, width * height * 3
        while (chunk := proc.stdout.read(size)) and len(chunk) == size:
            if n % 5 == 0:
                detections = model.predict(Image.fromarray(np.frombuffer(chunk, np.uint8).reshape(height, width, 3)),
                                           threshold=0.3)
                boxes[n] = [list(map(float, b)) for b, c in zip(detections.xyxy, detections.data["class_name"]) if c == "person"]
            n += 1
        proc.wait()
        cache[name] = boxes
        print(name, n, "frames,", sum(map(len, boxes.values())), "person boxes")
    OUT.write_text(json.dumps(cache))


if __name__ == "__main__":
    main()
