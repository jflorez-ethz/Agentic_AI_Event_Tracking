"""Build simulated posture-probe outputs (fixtures/) from labels.json, the CAVIAR XML and the videos' own PTS.

    .venv/bin/python experiments/fall_check/build_fixtures.py

For each case: the 20 probe times of rules.json around the 'after' frame, the first decoded frame at or after each
time, and for every person box in the XML at that frame (bags and other objects excluded): an opaque id, the labelled
posture and the box centre as (x, y) in [0, 1]. This is what a correct probe answer would contain. The fixtures are
committed, so the tests run without the source videos.
"""
import json
from pathlib import Path

from security_augmented.annotations import parse_annotations
from security_augmented.video import ingest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
import sys
sys.path.insert(0, str(HERE))
from decision import probe_times  # noqa: E402


def posture(segments, t):
    for a, b, p in segments:
        if a <= t < b:
            return p
    raise ValueError(f"no label at {t}")


def build(name, case):
    v = ingest(ROOT / "data/raw" / case["video"])
    tb = v.time_base_num / v.time_base_den
    pts = [(p - v.first_display_pts) * tb for p in v.frame_pts]
    frames = {f.number: f for f in parse_annotations(ROOT / "data/annotations" / case["xml"]).frames}
    t_before, t_after = case["pair"]
    out, focal_at_after = [], None
    for t in probe_times(t_after):
        n = next(i for i, p in enumerate(pts) if p >= t - 1e-6)
        persons = []
        for o in (frames[n].objects if n in frames else ()):
            role = " ".join(text for h in o.hypotheses for tag, text, _ in h.fields if tag == "role")
            if "object" in role:
                continue
            label = posture(case["segments"][o.id], pts[n]) if o.id in case["segments"] else case["others"]
            p = {"id": f"P{o.id}", "posture": label}
            if label != "not_visible":
                p.update(x=round(o.box.xc / v.width, 4), y=round(o.box.yc / v.height, 4))
            persons.append(p)
        out.append({"t": round(pts[n], 4), "frame": n, "persons": persons})
    after = min(out, key=lambda f: abs(f["t"] - t_after))
    focal = next((p for p in after["persons"] if p["id"] == f"P{case['focal']}" and "x" in p), None)
    if focal is None:  # focal not located at the after frame: take its nearest located frame
        located = [(abs(f["t"] - t_after), p) for f in out for p in f["persons"] if p["id"] == f"P{case['focal']}" and "x" in p]
        focal = min(located, key=lambda e: e[0])[1]
    return {"case": name, "video": case["video"], "video_sha256": v.sha256 if hasattr(v, "sha256") else None,
            "candidate": {"t_before": t_before, "t_after": t_after, "x": focal["x"], "y": focal["y"]},
            "expected": case["expected"], "probe": {"aspect": round(v.height / v.width, 4), "frames": out}}


def main():
    labels = json.loads((HERE / "labels.json").read_text())
    (HERE / "fixtures").mkdir(exist_ok=True)
    for name, case in labels["cases"].items():
        fx = build(name, case)
        (HERE / "fixtures" / f"{name}.json").write_text(json.dumps(fx, indent=1) + "\n")
        print(name, len(fx["probe"]["frames"]), "frames", fx["probe"]["frames"][0]["t"], "->", fx["probe"]["frames"][-1]["t"])


if __name__ == "__main__":
    main()
