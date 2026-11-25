"""Record what a correct posture probe would answer for each labelled case (fixtures/), by running the real
floor_check.check() against a simulated Perception built from labels.json, the CAVIAR XML and the videos' PTS.

    .venv/bin/python experiments/fall_check/build_fixtures.py

Each fixture holds the candidate anchor, the expected facts (written in labels.json before any run) and the
transcript of every probe and follow-up call: requested times and the answer (per frame, each person with an
opaque id, the labelled posture, the XML box centre x, y and size w, h in [0, 1], and seat_nearby: the
truth written in labels.json for the focal person, false for the others). Bags and other objects are excluded.
When the XML stops before the video (Rest_WiggleOnFloor), the person's last XML position is held. The tests
replay these transcripts without the source videos.
"""
import json
from pathlib import Path

from security_augmented import floor_check
from security_augmented.annotations import parse_annotations
from security_augmented.video import ingest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def posture(segments, t):
    for a, b, p in segments:
        if a <= t < b:
            return p
    raise ValueError(f"no label at {t}")


def simulator(case):
    video = ingest(ROOT / "data/raw" / case["video"])
    tb = video.time_base_num / video.time_base_den
    pts_us = [round((p - video.first_display_pts) * tb * 1_000_000) for p in video.frame_pts]
    frames = {f.number: f for f in parse_annotations(ROOT / "data/annotations" / case["xml"]).frames}
    focal, held = case["focal"], None
    transcript = []

    def boxes(n):
        out = {}
        for o in (frames[n].objects if n in frames else ()):
            role = " ".join(text for h in o.hypotheses for tag, text, _ in h.fields if tag == "role")
            if "object" not in role:
                out[o.id] = (round(o.box.xc / video.width, 4), round(o.box.yc / video.height, 4),
                             round(o.box.width / video.width, 4), round(o.box.height / video.height, 4))
        return out

    def ask(times_us, phase):
        nonlocal held
        answer = []
        for t in times_us:
            n = next(i for i, p in enumerate(pts_us) if p >= t)
            t_frame = pts_us[n] / 1_000_000
            present = boxes(n)
            if focal in present:
                held = present[focal]
            elif held is not None and n not in frames:  # XML ended: keep the last position of the focal person
                present[focal] = held
            persons = []
            for oid, (x, y, w, h) in sorted(present.items()):
                label = posture(case["segments"][oid], t_frame) if oid in case["segments"] else case["others"]
                if label != "not_visible":
                    persons.append({"id": f"P{oid}", "posture": label, "x": x, "y": y, "w": w, "h": h,
                                    "seat_nearby": oid == focal and case["seat_nearby_focal"]})
            answer.append({"t_us": pts_us[n], "display_index": n, "frame_id": f"frame-{n}", "persons": persons})
        answer = list({f["display_index"]: f for f in answer}.values())  # same frame requested twice
        inspection_id = f"sim-{len(transcript)}"
        transcript.append({"phase": phase, "times_us": list(times_us), "inspection_id": inspection_id, "frames": answer})
        return inspection_id, answer

    return video, ask, transcript


def build(name, case):
    video, ask, transcript = simulator(case)
    anchor = round(case["anchor_s"] * 1_000_000)
    candidate = f"cand-{name}"
    incidents = floor_check.check([(candidate, anchor)], ask, duration_us=video.duration_us,
                                  aspect=video.height / video.width, frame_size=(video.width, video.height),
                                  claimed=set() if case["first_look"] == "suspected" else {candidate})
    return {"case": name, "video": case["video"], "video_sha256": video.sha256, "duration_us": video.duration_us,
            "aspect": round(video.height / video.width, 4), "frame_size": [video.width, video.height],
            "first_look": case["first_look"], "anchor_us": anchor, "expected": case["expected_facts"],
            "transcript": transcript, "incidents": incidents}


def main():
    labels = json.loads((HERE / "labels.json").read_text())
    out = HERE / "fixtures"
    for old in out.glob("*.json"):
        old.unlink()
    for name, case in labels["cases"].items():
        fx = build(name, case)
        (out / f"{name}.json").write_text(json.dumps(fx, indent=1) + "\n")
        i = fx["incidents"][0]
        print(f"{name:26s} calls={len(fx['transcript'])} seen={i['seen']:24s} status={i['status']:16s} "
              f"signals={[x['code'] for x in i['doubt_signals']]}")


if __name__ == "__main__":
    main()
