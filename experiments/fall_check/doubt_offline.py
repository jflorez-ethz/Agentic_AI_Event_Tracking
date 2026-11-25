"""Offline computation of the floor_rules.json v3 doubt signals, before any implementation (criterion written first).

    .venv/bin/python experiments/fall_check/doubt_offline.py

Cases:
  - the 11 labelled cases (fixtures/): the close-check answers are SIMULATED from the posture labels and the XML
    boxes (an ideal close check); the "seat next to the person" answer is the truth written in labels.json;
  - the 4 incidents of the two check-in demo runs: REAL Gemini close-check answers (prompt floor-v1, which had no
    box and no seat field: the seat signal can only come from sitting_on_seat answers).
In both, the person's size and image-edge distance come from the CAVIAR XML box nearest to the answered position
(<= 0.15 of the width); live, they would come from Gemini's approximate box.
The thresholds are read from floor_rules.json (v3, commit 0907be1) and nothing here changes them.

Historical record: this script computed the v3 signals before any implementation (result: 7/9 known false
alerts marked, criterion not met; doubt_offline.json). v4 added no_floor_seen after seeing these results; the
production code (floor_check.doubt_signals) is re-checked on the same cases by tests/test_floor_check.py.
"""
import json
from math import hypot
from pathlib import Path
from statistics import median

from security_augmented import floor_check as fc
from security_augmented.annotations import parse_annotations

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
R = json.loads((ROOT / "src/security_augmented/floor_rules.json").read_text())
assert R["version"] in (3, 4)  # v4 thresholds are the v3 ones
D = R["doubt_signals"]
FLOOR, UPRIGHT = set(R["on_floor"]), set(R["upright"])
W, H = 384, 288


def xml_frames(xml):
    return {f.number: [o for o in f.objects
                       if "object" not in " ".join(t for h in o.hypotheses for tag, t, _ in h.fields if tag == "role")]
            for f in parse_annotations(ROOT / "data/annotations" / xml).frames}


def xml_box(people, x, y, aspect):
    near = min(people, key=lambda o: hypot(o.box.xc / W - x, (o.box.yc / H - y) * aspect), default=None)
    if near is None or hypot(near.box.xc / W - x, (near.box.yc / H - y) * aspect) > R["followup"]["link_max_distance"]:
        return None
    return near.box


def track(incident, aspect):
    """[(t_us, posture, person dict or None, frame)] for the checked person, probe by id, follow-ups by nearest position."""
    by_t = {f["t_us"]: f for f in incident["frames"]}
    out, last = [], None
    for s in incident.get("sequence", []):
        f = by_t.get(s["t_us"])
        p = None
        if f is not None and s["posture"] != "not_visible":
            if s["source"] == "probe":
                p = next((q for q in f["persons"] if q["id"] == incident["person"]), None)
            else:
                cand = [q for q in f["persons"] if q["posture"] == s["posture"]]
                p = min(cand, key=lambda q: fc._distance((q["x"], q["y"]), last, aspect)) if cand and last else None
        if p is not None:
            last = (p["x"], p["y"])
        out.append((s["t_us"], s["posture"], p, f, s["source"], last))
    return out


def signals(incident, *, first_look, aspect, xml, seat_truth=None):
    """List of (signal, measured value) for one incident. seat_truth: simulated answer of the seat field."""
    out = []
    if incident.get("reason") in ("probe_failed", "budget_exhausted"):
        return [("no_close_check", incident["reason"])]
    tr = track(incident, aspect)
    floor_seen = incident.get("first_floor_us") is not None
    if first_look == "claimed" and not floor_seen:
        out.append(("disagreement", "first look: on the floor; close check: nobody on the floor"))
    if first_look == "suspected" and floor_seen:
        out.append(("disagreement", "first look: only suspected; close check: someone on the floor"))
    seat_frames = [round(t / 1e6, 2) for t, p, *_ in tr if p == "sitting_on_seat"]
    if floor_seen:
        on = [x for x in tr if x[1] in FLOOR]
        if len(on) < D["few_floor_frames"]["min_frames"]:
            out.append(("few_floor_frames", f"{len(on)} frames on the floor"))
        o = incident["outcome"]
        visible_not_floor = o["kind"] == "stood_up" or (o["kind"] == "last_seen" and o.get("posture") not in FLOOR | {"not_visible"})
        if incident["floor_seconds"] < D["short_floor"]["min_s"] and visible_not_floor:
            out.append(("short_floor", f"{incident['floor_seconds']:.2f} s"))
        if not incident["arrival"]["observed"]:
            out.append(("arrival_not_seen", incident["arrival"]["why"]))
        boxes = [xml_box(xml.get(f["display_index"], []), p["x"], p["y"], aspect) for _, _, p, f, *_ in on if p and f]
        boxes = [b for b in boxes if b is not None]
        if boxes:
            h = median(b.height for b in boxes)
            if h < D["small_person"]["max_height_px"]:
                out.append(("small_person", f"{h:.0f} px"))
            gap = min(min(b.xc - b.width / 2, b.yc - b.height / 2, W - b.xc - b.width / 2, H - b.yc - b.height / 2) for b in boxes)
            if gap < D["image_edge"]["max_px"]:
                out.append(("image_edge", f"{max(gap, 0):.0f} px from the border"))
        else:
            out.append(("size_unmeasured", "no XML box near the answered position"))
        if incident["max_displacement"] > D["moving_on_floor"]["max_displacement"]:
            out.append(("moving_on_floor", f"{incident['max_displacement']:.0%} of the width"))
        visible = [p for _, p, *_ in tr if p != "not_visible"]
        state = [p in FLOOR for p in visible]
        if any(state[i] and not state[j] and state[k] for i in range(len(state)) for j in range(i + 1, len(state))
               for k in range(j + 1, len(state))):
            out.append(("posture_flicker", " → ".join(dict.fromkeys(visible))))
        for t, p, q, f, source, last in tr:
            if source == "followup" and f is not None and last is not None:
                n = sum(fc._distance((r["x"], r["y"]), last, aspect) <= D["identity_uncertain"]["max_distance"] for r in f["persons"])
                if n >= 2:
                    out.append(("identity_uncertain", f"{n} persons near the last position at {t / 1e6:.2f} s"))
                    break
    if seat_frames or seat_truth:
        out.append(("seat_nearby", f"sitting_on_seat at {seat_frames}" if seat_frames else "seat next to the person (simulated answer)"))
    return out


def simulated_cases():
    labels = json.loads((HERE / "labels.json").read_text())["cases"]
    first = {"browse1_edge": "suspected"}  # the held-out Browse1 alert was insufficient_evidence / possible person_fell
    for name, case in labels.items():
        fx = json.loads((HERE / "fixtures" / f"{name}.json").read_text())
        # Replay the recorded transcript through the current check() (no model call).
        answers = iter(fx["transcript"])
        incidents = fc.check([(f"cand-{name}", fx["anchor_us"])], lambda times, phase: (lambda c: (c["inspection_id"], c["frames"]))(next(answers)),
                             duration_us=fx["duration_us"], aspect=fx["aspect"])
        inc = incidents[0]
        # The simulated seat answer: true on the focal person's frames when labels.json says a seat touches them.
        seat = "any" if case["seat_nearby_focal"] else None
        truth = "false_alert" if not any(p in FLOOR for s in case["segments"].values() for _, _, p in s) else \
            ("clear_real" if name in ("fall_true", "wiggle_true", "fight_true") else "real_unclear")
        yield ("sim", name, truth, first.get(name, "claimed"), fx["aspect"], case["xml"], inc, seat)


def demo_cases():
    truth = {("Rest_FallOnFloor", 0): "false_alert", ("Rest_FallOnFloor", 1): "clear_real",
             ("Rest_SlumpOnFloor", 0): "false_alert", ("Rest_SlumpOnFloor", 1): "real_unclear"}
    xmlname = {"Rest_FallOnFloor.mpg": "Rest_FallOnFloor.xml", "Rest_SlumpOnFloor.mpg": "Rest_SlumpOnFloor.xml"}
    for run in sorted(ROOT.glob("experiments/demo_checkin.*/run")):
        a = json.loads((run / "analysis.json").read_text())["analysis"]
        v = a["video"]
        obs = {f["observation"]["id"]: f["observation"] for e in a["evidence"] for f in e["findings"]}
        name = Path(v["source_path"]).name
        for k, inc in enumerate(a["floor_incidents"]):
            claimed = any(obs[o]["category"] == fc.FLOOR_CATEGORY for o in inc["observation_ids"])
            yield ("live", f"{name.split('.')[0]}@{inc['anchor_us'] / 1e6:.1f}s", truth[(name.split(".")[0], k)],
                   "claimed" if claimed else "suspected", v["height"] / v["width"], xmlname[name], inc, None)


def main():
    rows = []
    for kind, name, truth, first, aspect, xml, inc, seat in [*simulated_cases(), *demo_cases()]:
        sig = signals(inc, first_look=first, aspect=aspect, xml=xml_frames(xml), seat_truth=seat)
        rows.append({"source": kind, "case": name, "truth": truth, "first_look": first, "floor_seen": inc.get("first_floor_us") is not None,
                     "look_closely": bool(sig), "signals": sig})
        print(f"{kind:4s} {name:28s} {truth:12s} first={first:9s} floor_seen={str(inc.get('first_floor_us') is not None):5s} "
              f"{'LOOK CLOSELY' if sig else 'no doubt signal':15s} {sig}")
    false = [r for r in rows if r["truth"] == "false_alert"]
    clear = [r for r in rows if r["truth"] == "clear_real"]
    print(f"\nKnown false alerts marked: {sum(r['look_closely'] for r in false)}/{len(false)} (criterion: all)")
    clear_by_case = {}
    for r in clear:
        clear_by_case.setdefault(r["source"], []).append(r["look_closely"])
    print(f"Clear real falls marked: simulated {sum(clear_by_case.get('sim', []))}/{len(clear_by_case.get('sim', []))}, "
          f"live {sum(clear_by_case.get('live', []))}/{len(clear_by_case.get('live', []))} (criterion: at most 1 of the 3)")
    print(f"Share of all cards marked: {sum(r['look_closely'] for r in rows)}/{len(rows)}; "
          f"real persons on the floor marked: {sum(r['look_closely'] for r in rows if r['truth'] != 'false_alert')}/"
          f"{sum(r['truth'] != 'false_alert' for r in rows)}")
    (HERE / "doubt_offline.json").write_text(json.dumps(rows, indent=1) + "\n")


if __name__ == "__main__":
    main()
