"""Code-side decision for a person_fell candidate from a neutral dense posture probe (rules.json).

The probe is Perception's answer to a neutral question: for each image, the posture of each visible person (imposed
vocabulary), a stable identifier (P1, P2...) and an approximate position (x, y in [0, 1] of width and height).
The question never contains the candidate's description or the word "fall". This module only applies the rules;
it never calls a model.

probe = {"aspect": height / width,
         "frames": [{"t": seconds, "persons": [{"id": "P1", "posture": "standing", "x": 0.4, "y": 0.6}, ...]}, ...]}
candidate = {"t_after": seconds, "x": optional, "y": optional}
"""
import json
from math import hypot
from pathlib import Path

RULES = json.loads((Path(__file__).with_name("rules.json")).read_text())
PRIORITY = RULES["reasons_in_priority_order"]


def probe_times(t_after, rules=RULES):
    """The 20 requested times: 8 every 250 ms before the 'after' frame, 12 every ~420 ms from it."""
    s = rules["probe_sampling"]
    return ([t_after + s["before"]["first_offset_s"] + i * s["before"]["step_s"] for i in range(s["before"]["count"])]
            + [t_after + s["after"]["first_offset_s"] + i * s["after"]["step_s"] for i in range(s["after"]["count"])])


def validate(probe, rules=RULES):
    """Return an error string, or None when the probe is well formed."""
    frames = probe.get("frames")
    if not isinstance(frames, list) or not frames or len(frames) > rules["probe_sampling"]["max_frames"]:
        return "frame count"
    times = [f.get("t") for f in frames]
    if any(not isinstance(t, (int, float)) for t in times) or times != sorted(times) or len(set(times)) != len(times):
        return "frame times"
    for f in frames:
        ids = [p.get("id") for p in f.get("persons", [])]
        if len(ids) != len(set(ids)):
            return "duplicate person id in one frame"
        for p in f["persons"]:
            if p.get("posture") not in rules["vocabulary"]:
                return f"unknown posture {p.get('posture')!r}"
            if p["posture"] != "not_visible" and not all(isinstance(p.get(k), (int, float)) and 0 <= p[k] <= 1 for k in ("x", "y")):
                return "position"
    return None


def tracks(probe):
    """{id: [(t, posture, x, y)]}, missing frames counting as not_visible."""
    out = {}
    ids = {p["id"] for f in probe["frames"] for p in f["persons"]}
    for f in probe["frames"]:
        seen = {p["id"]: p for p in f["persons"]}
        for pid in ids:
            p = seen.get(pid)
            out.setdefault(pid, []).append((f["t"], p["posture"] if p else "not_visible",
                                            p.get("x") if p else None, p.get("y") if p else None))
    return out


def _distance(a, b, aspect):
    return hypot(a[0] - b[0], (a[1] - b[1]) * aspect)


def evaluate_person(seq, aspect, rules=RULES):
    """Stage reached by one person's posture sequence, and the facts behind it."""
    upright, ground = set(rules["upright"]), set(rules["on_ground"])
    labels = [s[1] for s in seq]
    visible = [l for l in labels if l != "not_visible"]
    if not any(l in ground for l in labels):
        if visible and all(l in upright for l in visible):
            return {"reason": "upright_throughout"}
        if "kneeling" in visible:
            return {"reason": "kneeling_not_ground"}
        if "sitting_on_seat" in visible:
            return {"reason": "seated"}
        return {"reason": "no_ground"}
    j = labels.index(next(l for l in labels if l in ground))
    ups = [i for i in range(j) if labels[i] in upright]
    if not ups:
        return {"reason": "no_upright_before", "t_first_ground": seq[j][0]}
    i = ups[-1]
    facts = {"t_last_upright": seq[i][0], "t_first_ground": seq[j][0]}
    if seq[j][0] - seq[i][0] > rules["max_transition_s"]:
        return {"reason": "transition_too_slow", **facts}
    end, glitches, k = j, 0, j + 1
    while k < len(seq):
        if labels[k] in ground:
            end, glitches = k, 0
        elif labels[k] in upright:
            break
        else:
            glitches += 1
            if glitches > rules["max_glitch_frames_in_ground_run"]:
                break
        k += 1
    facts["t_ground_until"] = seq[end][0]
    if seq[end][0] - seq[j][0] < rules["min_ground_s"]:
        return {"reason": "ground_too_short", **facts}
    window = [s for s in seq[j:end + 1] if s[1] in ground and s[0] <= seq[j][0] + rules["min_ground_s"] + 1e-9]
    start = (window[0][2], window[0][3])
    moved = max(_distance(start, (s[2], s[3]), aspect) for s in window)
    facts["max_displacement"] = round(moved, 4)
    if moved > rules["max_ground_displacement"]:
        return {"reason": "moving_on_ground", **facts}
    return {"reason": "confirmed", **facts}


def _near(seq, candidate, aspect, rules):
    """Is this person near the candidate in space (position nearest t_after)?"""
    if candidate.get("x") is None or candidate.get("y") is None:
        return True
    located = [s for s in seq if s[2] is not None]
    if not located:
        return False
    s = min(located, key=lambda s: abs(s[0] - candidate["t_after"]))
    return _distance((s[2], s[3]), (candidate["x"], candidate["y"]), aspect) <= rules["near_candidate"]["max_distance"]


def decide(probe, candidate, rules=RULES):
    """{'verdict': 'supported'|'insufficient', 'reason', 'person', facts, 'timeline'} for one candidate.

    No probe (None) means no confirmation: the only path to 'supported' for person_fell is this function.
    """
    if probe is None:
        return {"verdict": "insufficient", "reason": "invalid_probe", "detail": "no posture probe", "timeline": {}}
    error = validate(probe, rules)
    if error:
        return {"verdict": "insufficient", "reason": "invalid_probe", "detail": error, "timeline": {}}
    aspect = probe.get("aspect", 0.75)
    lo, hi = rules["near_candidate"]["first_ground_from_after_s"]
    results = []
    for pid, seq in sorted(tracks(probe).items()):
        if not _near(seq, candidate, aspect, rules):
            continue
        r = evaluate_person(seq, aspect, rules)
        if r["reason"] == "confirmed" and not lo <= r["t_first_ground"] - candidate["t_after"] <= hi:
            r = {**r, "reason": "no_person_near"}
        results.append((pid, r))
    timeline = {pid: [(t, p) for t, p, _, _ in seq] for pid, seq in tracks(probe).items()}
    if not results:
        return {"verdict": "insufficient", "reason": "no_person_near", "timeline": timeline}
    pid, best = min(results, key=lambda pr: PRIORITY.index(pr[1]["reason"]))
    return {"verdict": "supported" if best["reason"] == "confirmed" else "insufficient",
            "person": pid, **best, "timeline": timeline}
