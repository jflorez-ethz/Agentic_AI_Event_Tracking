"""Blind test of trial 2 on a video never used during development (LeftBag_AtChair).

Nothing is tuned here: the detector is pilot.detect exactly as committed in 353dd40, with the frozen parameters
read from results_trial2.json and the fixed slow-model settings from pilot.TRIAL2_FIXED. The person filter is
computed for this video with the same RF-DETR Nano settings as persons.py (threshold 0.3, every 5th frame).

    .venv/bin/python experiments/stationary_objects/blind_test.py
"""
import json
import re
import subprocess

import numpy as np

import pilot
from videos import ANNOTATIONS, RAW

NAME, VIDEO, XML = "LeftBag_AtChair", "LeftBag_AtChair.mpg", "LeftBag_AtChair.xml"
HERE = pilot.HERE


def rfdetr_persons(path):
    from PIL import Image
    from rfdetr import RFDETRNano

    model = RFDETRNano()
    width, height = map(int, re.findall(r"\d+", subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout)[:2])
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough", "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE)
    boxes, n, size = {}, 0, width * height * 3
    while (chunk := proc.stdout.read(size)) and len(chunk) == size:
        if n % 5 == 0:
            detections = model.predict(Image.fromarray(np.frombuffer(chunk, np.uint8).reshape(height, width, 3)), threshold=0.3)
            boxes[n] = [list(map(float, b)) for b, c in zip(detections.xyxy, detections.data["class_name"]) if c == "person"]
        n += 1
    proc.wait()
    return boxes


def main():
    frozen = json.loads((HERE / "results_trial2.json").read_text())["frozen"]
    path = str(RAW / VIDEO)
    times = pilot.pts_times(path)
    events, xml_persons = pilot.truth(ANNOTATIONS / XML, times)
    cache = HERE / "persons_rfdetr_atchair.json"
    if not cache.exists():
        cache.write_text(json.dumps({NAME: rfdetr_persons(path)}))
    rfdetr = json.loads(cache.read_text())
    candidates, seconds = pilot.detect(path, times, stride=1, **frozen, **pilot.TRIAL2_FIXED,
                                       person_boxes=pilot.person_source("rfdetr", NAME, xml_persons, rfdetr))
    found, false = pilot.match(candidates, events)
    sheets = HERE / "sheets_blind_atchair"
    sheets.mkdir(exist_ok=True)
    for k, c in enumerate(candidates, 1):
        pilot.contact_sheet(path, c, sheets / f"candidate-{k:02d}.png")
    result = {"video": VIDEO, "xml": XML, "frozen": frozen, "fixed": pilot.TRIAL2_FIXED,
              "duration_s": round(times[-1], 2), "ground_truth": events, "events": found, "false_alarms": false,
              "candidates": candidates, "cpu_s_per_video_min": round(seconds / times[-1] * 60, 1)}
    (HERE / "results_blind_atchair.json").write_text(json.dumps(result, indent=2, default=str))
    print("ground truth:", [(e["type"], e["t"] and round(e["t"], 2), e["xy"]) for e in events])
    print("events:", [(e["type"], e["found"], e["time_error_s"]) for e in found])
    print("false alarms:", [(c["type"], round(c["t"], 2), tuple(round(v) for v in c["xy"])) for c in false])
    print("all candidates:", [(c["type"], round(c["t"], 2), tuple(round(v) for v in c["xy"])) for c in candidates])
    print("cpu s / video min:", result["cpu_s_per_video_min"])


if __name__ == "__main__":
    main()
