"""Offline pilot: class-agnostic left / removed / still-present object detection (plan detector C1, objects).

Dual background subtraction (OpenCV MOG2, slow vs fast). A pixel is static when the slow model calls it
foreground and the fast model has absorbed it. Static regions that persist for T seconds and are not covered by
a person become confirmed objects. Each object is then compared with the pre-object background (removed once
the area matches it again) and with its own appearance (present; anything else is occlusion). No model
provider call, no identity: a person is only a box used to suppress people standing still.

Criterion (written before running): an event is found when its type matches, the time is within ±2 s of the
CAVIAR XML (PTS) and the position within 20 px. Success means the three placements and the
LeftBag_PickedUp removal are found, LeftBox is reported as still present at the end, and there are
0 false alarms on the five videos without an object (raw count reported). LeftBag is the tuning video only.

    .venv/bin/python experiments/stationary_objects/pilot.py
"""
import csv
import json
import re
import subprocess
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from videos import ANNOTATIONS, RAW, TUNING, VIDEOS

HERE = Path(__file__).parent
TOLERANCE_S, TOLERANCE_PX = 2.0, 20.0
GONE_S = 1.5          # area back to the reference background for this long means removed
SLOW_S, FAST_S = 60.0, 2.0


def pts_times(video):
    return [float(t.rstrip(",")) for t in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout.split()]


def truth(xml, times):
    """Ground-truth object events and per-frame person boxes from a CAVIAR XML file."""
    frames = re.split(r'<frame number="', Path(xml).read_text())[1:]
    last = int(frames[-1].split('"')[0])
    objects, persons = {}, {}
    for frame in frames:
        n = int(frame.split('"')[0])
        for oid, body in re.findall(r'<object id="(\d+)">(.*?)</object>', frame, re.S):
            b = {k: int(v) for k, v in re.findall(r'(h|w|xc|yc)="(\d+)"', body)}
            role = (re.search(r"<role[^>]*>\s*([^<]*?)\s*</role>", body) or [0, ""])[1]
            box = (b["xc"] - b["w"] / 2, b["yc"] - b["h"] / 2, b["xc"] + b["w"] / 2, b["yc"] + b["h"] / 2)
            if "object" in role:
                objects.setdefault(oid, []).append((n, (b["xc"], b["yc"])))
            else:
                persons.setdefault(n, []).append(box)
    events = []
    for oid, track in objects.items():
        (n0, c0), (n1, c1) = track[0], track[-1]
        events.append({"type": "placed", "t": times[n0], "xy": c0, "object": oid})
        if n1 >= last - 2:
            events.append({"type": "present_at_end", "t": None, "xy": c1, "object": oid})
        else:
            events.append({"type": "removed", "t": times[min(n1 + 1, len(times) - 1)], "xy": c1, "object": oid})
    return events, persons


def match(candidates, events):
    """Greedy one-to-one matching by type, time (±2 s) and position (20 px)."""
    used, found = set(), []
    for event in events:
        best = None
        for k, c in enumerate(candidates):
            if k in used or c["type"] != event["type"]:
                continue
            if np.hypot(c["xy"][0] - event["xy"][0], c["xy"][1] - event["xy"][1]) > TOLERANCE_PX:
                continue
            if event["t"] is not None and abs(c["t"] - event["t"]) > TOLERANCE_S:
                continue
            error = 0.0 if event["t"] is None else abs(c["t"] - event["t"])
            if best is None or error < best[1]:
                best = (k, error)
        if best is not None:
            used.add(best[0])
        found.append({**event, "found": best is not None,
                      "time_error_s": None if best is None or event["t"] is None else round(best[1], 2)})
    false = [c for k, c in enumerate(candidates) if k not in used]
    return found, false


def frames(video, stride):
    w, h = map(int, re.findall(r"\d+", subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout)[:2])
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", video, "-fps_mode", "passthrough", "-f", "rawvideo",
                             "-pix_fmt", "bgr24", "pipe:1"], stdout=subprocess.PIPE)
    n = 0
    while (chunk := proc.stdout.read(w * h * 3)) and len(chunk) == w * h * 3:
        if n % stride == 0:
            yield n, np.frombuffer(chunk, np.uint8).reshape(h, w, 3)
        n += 1
    proc.wait()


def covered(box, persons, pad=6):
    x1, y1, x2, y2 = box
    return any(x1 < p[2] + pad and p[0] - pad < x2 and y1 < p[3] + pad and p[1] - pad < y2 for p in persons)


def detect(video, times, *, stride, static_s, min_area, person_boxes):
    """Candidate events for one video. person_boxes(n) returns person boxes for frame n, or None (no filter)."""
    fps = 25 / stride
    slow = cv2.createBackgroundSubtractorMOG2(history=int(SLOW_S * fps), varThreshold=25, detectShadows=True)
    fast = cv2.createBackgroundSubtractorMOG2(history=int(FAST_S * fps), varThreshold=25, detectShadows=True)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    history = deque(maxlen=int((static_s + FAST_S + 8) * fps))  # (n, gray) to date placements backwards
    counter, objects, candidates, last_n = None, [], [], 0
    started = time.monotonic()
    for n, frame in frames(video, stride):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.int16)
        history.append((n, gray))
        f_slow = slow.apply(frame, learningRate=1 / (SLOW_S * fps))
        f_fast = fast.apply(frame, learningRate=1 / (FAST_S * fps))
        counter = np.zeros(gray.shape, np.int32) if counter is None else counter
        static = (f_slow == 255) & (f_fast == 0)
        counter = np.where(static, counter + 1, np.where(f_slow == 255, counter, 0))  # occlusion keeps the count
        mask = cv2.morphologyEx(((counter >= static_s * fps) * 255).astype(np.uint8), cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        persons = person_boxes(n) if person_boxes else []
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
        for k in range(1, count):
            x, y, w, h, area = stats[k]
            if area < min_area or area > 2500:
                continue
            box, center = (x, y, x + w, y + h), tuple(map(float, centroids[k]))
            if any(np.hypot(center[0] - o["xy"][0], center[1] - o["xy"][1]) < 25 for o in objects if o["active"]):
                continue
            if person_boxes is not None and covered(box, persons):
                continue  # a person standing still, or an object still being handled: wait
            reference = slow.getBackgroundImage()
            ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY).astype(np.int16)[y:y + h, x:x + w]
            appearance = gray[y:y + h, x:x + w]
            placed = n
            for m, past in reversed(history):  # earliest time the area has differed from the reference since
                if np.mean(np.abs(past[y:y + h, x:x + w] - ref)) < 12:
                    break
                placed = m
            objects.append({"box": box, "xy": center, "ref": ref, "look": appearance, "active": True, "gone_since": None})
            candidates.append({"type": "placed", "t": times[placed], "xy": center, "frame": placed, "box": box})
        for o in objects:
            if not o["active"]:
                continue
            x1, y1, x2, y2 = o["box"]
            area = gray[y1:y2, x1:x2]
            to_ref, to_look = np.mean(np.abs(area - o["ref"])), np.mean(np.abs(area - o["look"]))
            if to_ref < 12 and to_ref < to_look:
                o["gone_since"] = o["gone_since"] if o["gone_since"] is not None else n
                if (n - o["gone_since"]) / 25 >= GONE_S:
                    o["active"] = False
                    candidates.append({"type": "removed", "t": times[o["gone_since"]], "xy": o["xy"],
                                       "frame": o["gone_since"], "box": o["box"]})
            else:
                o["gone_since"] = None
        last_n = n
    for o in objects:
        if o["active"]:
            candidates.append({"type": "present_at_end", "t": times[min(last_n, len(times) - 1)], "xy": o["xy"],
                               "frame": last_n, "box": o["box"]})
    return candidates, time.monotonic() - started


def person_source(kind, name, xml_persons, rfdetr):
    if kind == "none":
        return None
    if kind == "xml":
        return lambda n: xml_persons.get(n, [])
    boxes = {int(k): v for k, v in rfdetr[name].items()}
    return lambda n: boxes.get(n - n % 5, [])


def run_all(config, rfdetr, data):
    rows = []
    for name, video, xml in VIDEOS:
        times, events, persons = data[name]
        candidates, seconds = detect(str(RAW / video), times, stride=config["stride"], static_s=config["static_s"],
                                     min_area=config["min_area"],
                                     person_boxes=person_source(config["persons"], name, persons, rfdetr))
        found, false = match(candidates, events)
        rows.append({"video": name, "duration_s": round(times[-1], 1), "events": found, "false_alarms": false,
                     "candidates": candidates, "cpu_s_per_video_min": round(seconds / times[-1] * 60, 1)})
    return rows


def score(rows):
    positives = [r for r in rows if any(True for _ in r["events"])]
    negatives = [r for r in rows if not r["events"]]
    test = [e for r in positives if r["video"] != TUNING for e in r["events"]]
    return {
        "test_events_found": f'{sum(e["found"] for e in test)}/{len(test)}',
        "tuning_events_found": f'{sum(e["found"] for r in rows if r["video"] == TUNING for e in r["events"])}/'
                               f'{sum(1 for r in rows if r["video"] == TUNING for _ in r["events"])}',
        "false_alarms_negatives": sum(len(r["false_alarms"]) for r in negatives),
        "false_alarms_positives": sum(len(r["false_alarms"]) for r in positives),
        "criterion_met": all(e["found"] for e in test) and all(
            e["found"] for r in rows if r["video"] == TUNING for e in r["events"] if e["type"] == "placed")
        and sum(len(r["false_alarms"]) for r in negatives) == 0,
    }


def contact_sheet(video, candidate, path):
    """Before / at / after crops around a candidate, for blind review (no detector label on the image)."""
    x, y = map(int, candidate["xy"])
    picks = [max(0, candidate["frame"] - 75), candidate["frame"], candidate["frame"] + 75]
    tiles = []
    for n in picks:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-fps_mode", "passthrough", "-vf", f"select=eq(n\\,{n})",
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"], capture_output=True).stdout
        if not raw:
            continue
        h = len(raw) // 3 // 384
        frame = np.frombuffer(raw, np.uint8).reshape(h, 384, 3).copy()
        crop = frame[max(0, y - 40):y + 40, max(0, x - 40):x + 40]
        tiles.append(cv2.resize(crop, (240, 240), interpolation=cv2.INTER_NEAREST))
    if tiles:
        cv2.imwrite(str(path), np.hstack(tiles))


def table(rows):
    """Plain table of the main configuration: events, timing error, false alarms, CPU."""
    lines = ["| Video | Set | Events (XML) | Found | Time error | False alarms | CPU s / video min |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        kind = "tuning" if r["video"] == TUNING else ("test" if r["events"] else "no object")
        events = ", ".join(f'{e["type"]}' + (f' {e["t"]:.2f}s' if e["t"] is not None else "") for e in r["events"]) or "—"
        found = ", ".join("yes" if e["found"] else "MISSED" for e in r["events"]) or "—"
        errors = ", ".join("—" if e["time_error_s"] is None else f'{e["time_error_s"]} s' for e in r["events"]) or "—"
        false = "; ".join(f'{c["type"]} {c["t"]:.1f}s ({c["xy"][0]:.0f},{c["xy"][1]:.0f})' for c in r["false_alarms"])
        lines.append(f'| {r["video"]} | {kind} | {events} | {found} | {errors} | {len(r["false_alarms"])}'
                     f'{" — " + false if false else ""} | {r["cpu_s_per_video_min"]} |')
    return "\n".join(lines)


def main(argv=None):
    import sys

    main_only = "--main-only" in (sys.argv[1:] if argv is None else argv)
    rfdetr = json.loads((HERE / "persons_rfdetr_stride5.json").read_text())
    data = {}
    for name, video, xml in VIDEOS:
        times = pts_times(str(RAW / video))
        events, persons = truth(ANNOTATIONS / xml, times)
        data[name] = (times, events, persons)
    # 1. Tune on LeftBag only (person filter: RF-DETR, 25 fps), then freeze.
    tuning = []
    for static_s in (3, 5, 8):
        for min_area in (30, 60, 120):
            config = {"stride": 1, "static_s": static_s, "min_area": min_area, "persons": "rfdetr"}
            name, video, xml = VIDEOS[0]
            times, events, persons = data[name]
            candidates, _ = detect(str(RAW / video), times, stride=1, static_s=static_s, min_area=min_area,
                                   person_boxes=person_source("rfdetr", name, persons, rfdetr))
            found, false = match(candidates, events)
            tuning.append({**config, "found": sum(e["found"] for e in found), "false": len(false)})
    best = max(tuning, key=lambda r: (r["found"], -r["false"], -r["static_s"]))
    frozen = {"static_s": best["static_s"], "min_area": best["min_area"]}
    print("tuning on LeftBag:", tuning, "\nfrozen:", frozen)
    if main_only:
        rows = run_all({"stride": 1, "persons": "rfdetr", **frozen}, rfdetr, data)
        (HERE / "results_main.json").write_text(json.dumps(
            {"criterion": __doc__.split("Criterion (written before running): ")[1].split("\n\n")[0],
             "tuning": tuning, "frozen": frozen, "score": score(rows), "videos": rows}, indent=2, default=str))
        print(table(rows))
        print("score:", score(rows))
        return
    # 2. Frozen parameters on every video, with ablations.
    results = {"criterion": __doc__.split("Criterion (written before running): ")[1].split("\n\n")[0],
               "tuning": tuning, "frozen": frozen, "runs": {}}
    for persons in ("rfdetr", "xml", "none"):
        for stride in (1, 5):
            config = {"stride": stride, "persons": persons, **frozen}
            rows = run_all(config, rfdetr, data)
            key = f"persons={persons},fps={25 // stride}"
            results["runs"][key] = {"config": config, "score": score(rows), "videos": rows}
            print(key, results["runs"][key]["score"])
    # 3. Sensitivity to T with the main configuration (RF-DETR persons, 25 fps).
    results["sensitivity_T"] = {}
    for static_s in (2, 3, 5, 8, 12):
        rows = run_all({"stride": 1, "persons": "rfdetr", "static_s": static_s, "min_area": frozen["min_area"]}, rfdetr, data)
        results["sensitivity_T"][static_s] = score(rows)
    (HERE / "results.json").write_text(json.dumps(results, indent=2, default=str))
    # 4. Blind review material for the main configuration.
    main_rows = results["runs"]["persons=rfdetr,fps=25"]["videos"]
    sheets = HERE / "sheets"
    sheets.mkdir(exist_ok=True)
    with (HERE / "blind_review.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate", "video", "time_s", "x", "y", "sheet", "reviewer_label (placed / removed / still there / nothing)"])
        k = 0
        for row in main_rows:
            video = str(RAW / next(v for n, v, _ in VIDEOS if n == row["video"]))
            for c in row["candidates"]:
                k += 1
                sheet = sheets / f"candidate-{k:02d}.png"
                contact_sheet(video, c, sheet)
                writer.writerow([k, row["video"], round(c["t"], 2), round(c["xy"][0]), round(c["xy"][1]), sheet.name, ""])
    print("criterion met (main):", results["runs"]["persons=rfdetr,fps=25"]["score"])


if __name__ == "__main__":
    main()
