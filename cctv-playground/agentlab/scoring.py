"""Score one model answer (list of events) against one labelled test item.

Rules (agreed 21 Nov 2026 after the step 3 hand runs):
- Real label: correct if the answer has a REAL event of the same type that STARTS within
  START_TOL_S of the label's start. Right type at the wrong time does not count (step 3 run 3
  and the step 4 smoke test pointed at a decoy bag 15-19 s early); it is reported as type_only.
  An overlap test was too lenient: "8-70 s" overlaps a label of "27-70 s".
- Look-alike label: correct if the answer raises no REAL event of that type at that time
  (no false alarm). Naming it as a look-alike is reported as recognised.
- none label: correct if no real event is raised, except after_hours_person: the only "none"
  window (G336 5-55 s) has people far away by a building outside the zone, and the prompt
  has no zones yet. People reported there are counted in people_outside_zone.
- top1: the matching event is the first one in the list (what the agent would act on first).
"""
from __future__ import annotations

TOLERANCE_S = 3.0   # margin for the overlap test (false alarms on look-alikes)
START_TOL_S = 5.0   # a real event is found only if it starts this close to the label's start


def _overlaps(e: dict, start: float, end: float) -> bool:
    return e["start_s"] <= end + TOLERANCE_S and e["end_s"] >= start - TOLERANCE_S


def score(item: dict, result: dict) -> dict:
    """item: one row of testset.csv (type, real, start_s, end_s). result: parsed answer with 'events'."""
    events = result.get("events", [])
    typ, real = item["type"], str(item["real"]).lower() == "true"
    start, end = float(item["start_s"]), float(item["end_s"])
    out = {"correct": False, "top1": False, "start_err": None, "type_only": False,
           "recognised": False, "false_alarm": False, "people_outside_zone": False,
           "missed_critical": False, "n_events": len(events)}

    if result.get("video_missing"):
        out["missed_critical"] = typ == "person_down" and real
        return out

    if typ == "none":
        alarms = [e for e in events if e["real"] and e["event_type"] != "after_hours_person"]
        out["false_alarm"] = bool(alarms)
        out["people_outside_zone"] = any(e["real"] and e["event_type"] == "after_hours_person" for e in events)
        out["correct"] = not alarms
        return out

    same = [e for e in events if e["event_type"] == typ]
    if real:
        hits = [e for e in same if e["real"] and abs(e["start_s"] - start) <= START_TOL_S]
        out["correct"] = bool(hits)
        out["top1"] = bool(hits) and events[0] in hits
        out["type_only"] = not hits and any(e["real"] for e in same)
        if hits:
            out["start_err"] = round(min(abs(e["start_s"] - start) for e in hits), 1)
        out["missed_critical"] = typ == "person_down" and not hits
    else:
        alarms = [e for e in same if e["real"] and _overlaps(e, start, end)]
        looks = [e for e in same if not e["real"] and _overlaps(e, start, end)]
        out["false_alarm"] = bool(alarms)
        out["recognised"] = bool(looks)
        out["correct"] = not alarms
        out["top1"] = bool(looks) and events[0] in looks
    return out
