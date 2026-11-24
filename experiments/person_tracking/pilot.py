"""Offline pilot: anonymous person tracks ("Person A", "Person B"...) within one video.

RF-DETR Nano person detections (cached) -> supervision ByteTrack (motion and box overlap only, no appearance
embedding) -> stitching of short breaks at the same place -> removal of tracks that never move (fixtures seen as
people) -> labels A, B, C... in order of first appearance. Labels are valid inside one video only; nothing links
videos, faces or gait. No model provider call. The pipeline is not modified.

Criterion (written before running; IoU >= 0.5 for a detection to match an XML box):
1. Owner test on the two test videos with a bag (4 checks): LeftBag_PickedUp, the person setting the bag down
   and the person picking it up (one continuous XML track) get the same label; LeftBag_AtChair, they (two XML
   tracks) get two different labels, each matched to its own XML track. No false "same person" claim.
2. IDF1 >= 0.70 over the seven test videos with RF-DETR detections, pooled (2*sum IDTP / (sum truth + sum predicted
   detections)), the standard set-level IDF1.
3. The same figures with XML boxes as detections (oracle) are reported alongside.
Tuning uses Walk2 and LeftBag only.

    .venv/bin/python experiments/person_tracking/pilot.py
"""
import json
import xml.etree.ElementTree as ET
import subprocess
from itertools import product
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from detections import ANNOTATIONS, RAW, VIDEOS

HERE = Path(__file__).parent
STRIDE, FPS = 5, 5.0
IOU = 0.5


def pts_times(video):
    return [float(t.rstrip(",")) for t in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout.split()]


def ground_truth(xml):
    """Read person and bag boxes in original frame coordinates."""
    persons, bag = {}, {}
    for frame in ET.parse(xml).getroot().findall("frame"):
        n = int(frame.attrib["number"])
        for obj in frame.findall("objectlist/object"):
            bounds = obj.find("box").attrib
            x, y, w, h = (int(bounds[k]) for k in ("xc", "yc", "w", "h"))
            box = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
            role = obj.findtext(".//role", default="")
            (bag if "object" in role else persons.setdefault(obj.attrib["id"], {}))[n] = box
    return persons, bag


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def track(detections, *, activation, lost_s, matching):
    """ByteTrack over cached detections {frame: [[x1,y1,x2,y2,conf],...]} -> {track: {frame: box}}."""
    import supervision as sv

    tracker = sv.ByteTrack(track_activation_threshold=activation, lost_track_buffer=max(1, round(lost_s * FPS)),
                           minimum_matching_threshold=matching, frame_rate=round(FPS), minimum_consecutive_frames=1)
    tracks = {}
    for n in sorted(detections, key=int):
        rows = np.array(detections[n], dtype=float).reshape(-1, 5)
        dets = sv.Detections(xyxy=rows[:, :4], confidence=rows[:, 4], class_id=np.zeros(len(rows), dtype=int))
        out = tracker.update_with_detections(dets)
        for box, tid in zip(out.xyxy, out.tracker_id):
            tracks.setdefault(int(tid), {})[int(n)] = tuple(map(float, box))
    return tracks


def stitch(tracks, times, *, tau_s, base_px, speed_px_s=40.0):
    """Join a track that starts shortly after another ended, at a compatible place and size."""
    if tau_s <= 0:
        return tracks
    order = sorted(tracks, key=lambda t: min(tracks[t]))
    merged, owner = {t: dict(tracks[t]) for t in order}, {}
    for t in order:
        start = min(merged[t]) if t in merged else None
        if start is None:
            continue
        best = None
        for p in merged:
            if p == t or max(merged[p]) >= start:
                continue
            end = max(merged[p])
            gap = times[start] - times[end]
            if gap > tau_s:
                continue
            a, b = merged[p][end], merged[t][start]
            distance = np.hypot(*np.subtract(center(a), center(b)))
            area_a, area_b = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
            if distance > base_px + speed_px_s * gap or not 0.4 <= area_b / max(area_a, 1e-6) <= 2.5:
                continue
            if best is None or distance < best[1]:
                best = (p, distance)
        if best is not None:
            merged[best[0]].update(merged.pop(t))
    return merged


def drop_static(tracks, *, min_move_px=12.0):
    """Remove tracks that never move: fixtures detected as people."""
    kept = {}
    for t, boxes in tracks.items():
        first = center(boxes[min(boxes)])
        if max(np.hypot(*np.subtract(center(b), first)) for b in boxes.values()) >= min_move_px:
            kept[t] = boxes
    return kept


def label(tracks):
    order = sorted(tracks, key=lambda t: min(tracks[t]))
    names = {}
    for k, t in enumerate(order):
        names[t] = "Person " + (chr(65 + k) if k < 26 else f"{chr(64 + k // 26)}{chr(65 + k % 26)}")
    return names


def frame_matches(truth, predicted, frames):
    """Per-frame optimal matching {(gt, frame): pred} at IoU >= 0.5."""
    matched = {}
    for n in frames:
        gts = [g for g in truth if n in truth[g]]
        prs = [p for p in predicted if n in predicted[p]]
        if not gts or not prs:
            continue
        cost = np.array([[1 - iou(truth[g][n], predicted[p][n]) for p in prs] for g in gts])
        for i, j in zip(*linear_sum_assignment(cost)):
            if 1 - cost[i, j] >= IOU:
                matched[(gts[i], n)] = prs[j]
    return matched


def evaluate(truth, predicted, frames):
    """IDF1 (optimal track-to-track assignment), identity switches and per-truth-track numbers."""
    frames = sorted(frames)
    gt_count = sum(1 for g in truth for n in truth[g] if n in frames)
    pr_count = sum(1 for p in predicted for n in predicted[p] if n in frames)
    gids, pids = list(truth), list(predicted)
    together = np.zeros((len(gids), len(pids)))
    for n in frames:
        for i, g in enumerate(gids):
            if n not in truth[g]:
                continue
            for j, p in enumerate(pids):
                if n in predicted[p] and iou(truth[g][n], predicted[p][n]) >= IOU:
                    together[i, j] += 1
    idtp = together[linear_sum_assignment(-together)].sum() if together.size else 0.0
    idf1 = 2 * idtp / (gt_count + pr_count) if gt_count + pr_count else 1.0
    matched = frame_matches(truth, predicted, frames)
    switches, per_track = 0, {}
    for g in gids:
        sequence = [matched[(g, n)] for n in frames if (g, n) in matched]
        switches += sum(1 for a, b in zip(sequence, sequence[1:]) if a != b)
        per_track[g] = {"frames": sum(1 for n in frames if n in truth[g]), "matched": len(sequence),
                        "numbers": len(set(sequence))}
    return {"idf1": round(idf1, 3), "idtp": float(idtp), "truth_detections": gt_count, "predicted_detections": pr_count,
            "id_switches": switches, "truth_tracks": len(gids),
            "predicted_tracks": len(pids), "per_truth_track": per_track}, matched


def owners(truth, bag):
    """XML person nearest to the bag at its first (set down) and last (picked up) frames."""
    if not bag:
        return None
    first, last = min(bag), max(bag)

    def nearest(n):
        options = []
        for g, boxes in truth.items():
            near = [k for k in boxes if abs(k - n) <= 12]
            if near:
                k = min(near, key=lambda k: abs(k - n))
                options.append((np.hypot(*np.subtract(center(boxes[k]), center(bag[n]))), g))
        return min(options)[1] if options else None
    return {"placed_by": nearest(first), "placed_frame": first, "picked_by": nearest(last), "picked_frame": last}


def label_at(matched, names, gt, n, window):
    """Predicted label of an XML person around frame n (closest matched processed frame within the window)."""
    candidates = sorted((abs(k - n), p) for (g, k), p in matched.items() if g == gt and abs(k - n) <= window)
    return names.get(candidates[0][1]) if candidates else None


def run_video(name, video, xml, detections, params, *, oracle=False):
    times = pts_times(str(RAW / video))
    truth, bag = ground_truth(ANNOTATIONS / xml)
    frames = {n for n in range(0, len(times), STRIDE)}
    if oracle:
        detections = {str(n): [[*truth[g][n], 0.95] for g in truth if n in truth[g]] for n in sorted(frames)}
    predicted = track(detections, activation=params["activation"], lost_s=params["lost_s"], matching=params["matching"])
    predicted = drop_static(stitch(predicted, times, tau_s=params["tau_s"], base_px=params["base_px"]))
    names = label(predicted)
    metrics, matched = evaluate(truth, predicted, frames)
    owner = owners(truth, bag)
    if owner:
        window = int(1.5 * 25)
        owner["placed_label"] = label_at(matched, names, owner["placed_by"], owner["placed_frame"], window)
        owner["picked_label"] = label_at(matched, names, owner["picked_by"], owner["picked_frame"], window)
        owner["placed_s"], owner["picked_s"] = round(times[owner["placed_frame"]], 2), round(times[owner["picked_frame"]], 2)
    return {"video": name, "metrics": metrics, "owner": owner,
            "tracks": {names[t]: {"first_s": round(times[min(b)], 2), "last_s": round(times[max(b)], 2), "detections": len(b)}
                       for t, b in predicted.items()}}


def owner_checks(rows):
    """The four pre-registered owner checks on the two test videos with a bag."""
    by = {r["video"]: r["owner"] for r in rows}
    checks = []
    p = by.get("LeftBag_PickedUp")
    if p:
        checks += [("PickedUp: owner labelled at set-down", p["placed_label"] is not None),
                   ("PickedUp: same label at pick-up (one XML track)",
                    p["picked_label"] is not None and p["picked_label"] == p["placed_label"])]
    a = by.get("LeftBag_AtChair")
    if a:
        checks += [("AtChair: owner labelled at set-down", a["placed_label"] is not None),
                   ("AtChair: different label at pick-up (two XML tracks)",
                    a["picked_label"] is not None and a["picked_label"] != a["placed_label"])]
    return checks


# Clips excluded from the five-clip subset. The "offset" once blamed on their annotation was a reader bug (see
# xml_correction.md); the subset is kept only to reproduce the recorded five-clip results.
MISALIGNED = {"TwoEnterShop1front", "Meet_WalkSplit"}


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--detections", default="detections_stride5.json")
    parser.add_argument("--aligned-only", action="store_true", help="Measure the criterion on the historical five-clip test subset")
    parser.add_argument("--output", default="results.json")
    args = parser.parse_args(argv)
    detections = json.loads((HERE / args.detections).read_text())
    videos = [v for v in VIDEOS if not (args.aligned_only and v[0] in MISALIGNED)]
    roles = {name: role for name, _, _, role in videos}
    # 1. Tune on Walk2 and LeftBag only (RF-DETR detections).
    grid = []
    for activation, lost_s, matching, tau_s, base_px in product((0.25, 0.4), (1.0, 2.0, 4.0), (0.6, 0.8),
                                                                (0.0, 1.0, 2.0, 3.0), (20.0, 40.0)):
        params = {"activation": activation, "lost_s": lost_s, "matching": matching, "tau_s": tau_s, "base_px": base_px}
        scores = [run_video(n, v, x, detections[n], params)["metrics"] for n, v, x, r in videos if r == "tuning"]
        grid.append({**params, "mean_idf1": round(float(np.mean([s["idf1"] for s in scores])), 3),
                     "id_switches": sum(s["id_switches"] for s in scores)})
    best = max(grid, key=lambda g: (g["mean_idf1"], -g["id_switches"]))
    frozen = {k: best[k] for k in ("activation", "lost_s", "matching", "tau_s", "base_px")}
    no_stitch = max((g for g in grid if g["tau_s"] == 0.0), key=lambda g: (g["mean_idf1"], -g["id_switches"]))
    print("frozen (tuned on Walk2 + LeftBag):", frozen, "| tuning mean IDF1", best["mean_idf1"],
          "| best without stitching", no_stitch["mean_idf1"])
    # 2. Frozen on every video: RF-DETR, oracle (XML boxes) and no stitching.
    results = {"criterion": __doc__.split("Criterion (written before running; ")[1].split("\n\n")[0],
               "detections": args.detections, "aligned_only": args.aligned_only, "cpu": detections.get("_cpu"),
               "frozen": frozen, "tuning_grid": grid, "runs": {}}
    for variant, kwargs, params in (("rfdetr", {}, frozen), ("oracle", {"oracle": True}, frozen),
                                    ("rfdetr_no_stitch", {}, {**frozen, "tau_s": 0.0})):
        rows = []
        for name, video, xml, role in videos:
            row = run_video(name, video, xml, detections.get(name, {}), params, **kwargs)
            row["role"] = role
            rows.append(row)
        test = [r for r in rows if r["role"] == "test"]
        checks = owner_checks(rows)
        pooled = round(2 * sum(r["metrics"]["idtp"] for r in test) / sum(
            r["metrics"]["truth_detections"] + r["metrics"]["predicted_detections"] for r in test), 3)
        results["runs"][variant] = {
            "rows": rows, "owner_checks": checks,
            "test_pooled_idf1": pooled,
            "test_id_switches": sum(r["metrics"]["id_switches"] for r in test),
            "criterion_met": all(ok for _, ok in checks) and len(checks) == 4
            and pooled >= 0.70,
        }
    (HERE / args.output).write_text(json.dumps(results, indent=2, default=str))
    for variant, run in results["runs"].items():
        print(f"\n== {variant}: test pooled IDF1 {run['test_pooled_idf1']}, test switches {run['test_id_switches']}, "
              f"criterion met: {run['criterion_met']}")
        for r in run["rows"]:
            m, o = r["metrics"], r["owner"]
            owner = (f" | set down by XML {o['placed_by']} -> {o['placed_label']} at {o['placed_s']}s; picked up by XML "
                     f"{o['picked_by']} -> {o['picked_label']} at {o['picked_s']}s") if o else ""
            print(f"  {r['role']:6} {r['video']:20} IDF1 {m['idf1']:.3f} switches {m['id_switches']:3} "
                  f"truth/pred tracks {m['truth_tracks']}/{m['predicted_tracks']}{owner}")
        for text, ok in run["owner_checks"]:
            print(f"  [{'x' if ok else ' '}] {text}")


if __name__ == "__main__":
    main()
