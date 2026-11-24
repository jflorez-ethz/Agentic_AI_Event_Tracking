"""Offline tracking pilot: RF-DETR (Apache-2.0) + ByteTrack (supervision) against CAVIAR XML tracks.

Local only: no network after the weights are cached, no model provider call. ByteTrack uses box motion
and overlap only (no appearance embedding), so track numbers are anonymous and valid within one video.

    .venv/bin/python experiments/tracking_pilot/pilot.py data/raw/LeftBag_PickedUp.mpg \
        data/annotations/lbpugt.xml --stride 5 --output experiments/tracking_pilot/leftbag_pickedup-stride5.json
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np

KEEP = {"person", "backpack", "handbag", "suitcase"}


def xml_tracks(path):
    """CAVIAR ground truth: {object id: {frame: (x1, y1, x2, y2)}} plus a kind per object."""
    boxes, kinds = {}, {}
    for frame in re.split(r'<frame number="', Path(path).read_text())[1:]:
        n = int(frame.split('"')[0])
        for oid, body in re.findall(r'<object id="(\d+)">(.*?)</object>', frame, re.S):
            b = {k: int(v) for k, v in re.findall(r'(h|w|xc|yc)="(\d+)"', body)}
            boxes.setdefault(oid, {})[n] = (b["xc"] - b["w"] / 2, b["yc"] - b["h"] / 2,
                                            b["xc"] + b["w"] / 2, b["yc"] + b["h"] / 2)
            role = (re.search(r"<role[^>]*>\s*([^<]*?)\s*</role>", body) or [0, ""])[1]
            if "object" in role:
                kinds[oid] = "object"
    return boxes, {oid: kinds.get(oid, "person") for oid in boxes}


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def evaluate(truth, kinds, predicted, frames, threshold=0.3, times=None):
    """Per ground-truth track: coverage, distinct predicted track numbers and identity switches."""
    report = {}
    for oid, by_frame in truth.items():
        ids, matched, evaluated, at = [], 0, 0, []
        for n in sorted(by_frame):
            if n not in frames:
                continue
            evaluated += 1
            best = max(predicted.get(n, []), key=lambda p: iou(p["box"], by_frame[n]), default=None)
            if best is not None and iou(best["box"], by_frame[n]) >= threshold:
                matched += 1
                ids.append(best["track"])
                at.append(n)
        changes = [at[k + 1] for k in range(len(ids) - 1) if ids[k] != ids[k + 1]]
        switches = len(changes)
        dominant = max((ids.count(i) for i in set(ids)), default=0)
        report[oid] = {"kind": kinds[oid], "frames_evaluated": evaluated, "coverage": round(matched / evaluated, 3) if evaluated else None,
                       "distinct_track_numbers": len(set(ids)), "identity_switches": switches,
                       "dominant_number_share": round(dominant / evaluated, 3) if evaluated else None,
                       "switch_frames": changes,
                       **({"switch_seconds": [round(times[n], 2) for n in changes]} if times else {})}
    return report


def run(video, stride, threshold):
    import supervision as sv
    from PIL import Image
    from rfdetr import RFDETRNano

    width, height = map(int, re.findall(r"\d+", subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout)[:2])
    model = RFDETRNano()
    tracker = sv.ByteTrack(frame_rate=max(1, round(25 / stride)))
    process = subprocess.Popen(["ffmpeg", "-v", "error", "-i", video, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                               stdout=subprocess.PIPE)
    predicted, frames, seconds, n = {}, set(), 0.0, 0
    size = width * height * 3
    while chunk := process.stdout.read(size):
        if len(chunk) < size:
            break
        if n % stride == 0:
            image = Image.fromarray(np.frombuffer(chunk, np.uint8).reshape(height, width, 3))
            started = time.monotonic()
            detections = model.predict(image, threshold=threshold)
            keep = np.array([name in KEEP for name in detections.data["class_name"]], dtype=bool)
            tracked = tracker.update_with_detections(detections[keep])
            seconds += time.monotonic() - started
            frames.add(n)
            predicted[n] = [{"box": tuple(map(float, box)), "track": int(track), "class": str(name)}
                            for box, track, name in zip(tracked.xyxy, tracked.tracker_id,
                                                        tracked.data.get("class_name", ["?"] * len(tracked)))]
        n += 1
    process.wait()
    return predicted, frames, seconds, n


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("xml")
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    truth, kinds = xml_tracks(args.xml)
    predicted, frames, seconds, total = run(args.video, args.stride, args.threshold)
    times = [float(t.rstrip(",")) for t in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time", "-of", "csv=p=0", args.video],
        capture_output=True, text=True, check=True).stdout.split()]
    result = {
        "video": args.video, "xml": args.xml, "model": "RF-DETR Nano (COCO weights)", "tracker": "supervision ByteTrack",
        "stride": args.stride, "threshold": args.threshold, "frames_decoded": total, "frames_processed": len(frames),
        "cpu_seconds_detect_and_track": round(seconds, 1),
        "seconds_per_video_minute": round(seconds / (total / 25) * 60, 1),
        "predicted_track_numbers": len({p["track"] for ps in predicted.values() for p in ps}),
        "per_truth_track": evaluate(truth, kinds, predicted, frames, times=times),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "per_truth_track"}, indent=1))
    for oid, row in result["per_truth_track"].items():
        print(f"  truth object {oid} ({row['kind']}): {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
