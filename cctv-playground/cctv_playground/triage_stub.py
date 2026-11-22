"""Placeholder triage, so the pipeline runs end to end today.

It is a fixed set of rules, not an agent: it never looks at the video. It exists to show
the plumbing: a candidate comes in, tools are called on the replay clock, a verdict with
a reason and evidence goes to the inbox.

Task D2 replaces `triage` with the model-driven agent. Keep the signature and the
returned dict, and give the agent the same AgentTools methods as its tools.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .tools import AgentTools

AFTER_HOURS = {"after_hours_person", "after_hours_vehicle"}
NEVER_DISMISS = {"person_down", "fire"}
LINK_WINDOW = timedelta(minutes=5)

KIND_LABELS = {
    "after_hours_person": "Person after hours",
    "after_hours_vehicle": "Vehicle after hours",
    "person_down": "Person down",
    "fire": "Fire or smoke",
    "blocked_exit": "Blocked exit",
}


def _hms(t: datetime) -> str:
    return t.strftime("%H:%M:%S")


def triage(candidate: dict, tools: AgentTools, open_alerts: list[dict]) -> dict:
    t0 = datetime.fromisoformat(candidate["first_seen"])
    t1 = datetime.fromisoformat(candidate["detected_at"])
    kind = candidate["kind"]
    cameras = {c["id"]: c for c in tools.list_cameras()}
    cam = cameras[candidate["camera_id"]]

    evidence = []
    clip = tools.get_clip(cam["id"], _hms(t0 - timedelta(seconds=20)), _hms(t1))
    if "path" in clip:
        evidence.append(clip["path"])

    def result(verdict: str, priority: str, reason: str, linked_to: str | None = None) -> dict:
        return {"verdict": verdict, "priority": priority, "reason": reason,
                "evidence": evidence, "linked_to": linked_to}

    if kind in NEVER_DISMISS:
        return result("escalate", "high", f"{KIND_LABELS.get(kind, kind)} on {cam['id']}. "
                      "Safety events are never dismissed by the agent; send the nearest guard.")

    if kind == "blocked_exit":
        return result("escalate", "medium", f"Emergency exit covered by {cam['id']} appears obstructed. "
                      "Supervisor to have it cleared and logged.")

    if kind in AFTER_HOURS:
        # Same intruder seen a moment ago on a neighbouring camera? Add to that alert, don't raise a new one.
        for alert in open_alerts:
            seen = datetime.fromisoformat(alert["candidate"]["first_seen"])
            gap = abs(seen - t0).total_seconds()
            if alert["candidate"]["camera_id"] in cam["neighbors"] and gap <= LINK_WINDOW.total_seconds():
                ago = f"{int(gap)} s" if gap < 120 else f"{int(gap // 60)} min"
                return result("linked", alert["priority"],
                              f"Activity on {cam['id']} follows alert {alert['id']} on neighbouring camera "
                              f"{alert['candidate']['camera_id']} {ago} earlier. Added to that alert.",
                              linked_to=alert["id"])

        swipes = []
        for door in cam["doors"]:
            log = tools.access_log(_hms(t0 - timedelta(minutes=10)), _hms(t1), door)
            swipes += log.get("rows", [])
        shifts = [r for r in tools.roster(_hms(t0)).get("rows", [])
                  if cam["zone"].lower() in r.get("zones", "").lower()]

        if swipes or shifts:
            parts = [f"badge {s['badge']} ({s.get('holder', 'unknown')}) at {s['door']} {s['time']}" for s in swipes]
            parts += [f"roster: {s['who']}, {s['role']}, {s['start']} to {s['end']}" for s in shifts]
            return result("dismiss", "low", f"Expected activity in {cam['zone']}: " + "; ".join(parts) + ".")

        for neighbor in cam["neighbors"]:
            extra = tools.get_clip(neighbor, _hms(t0 - timedelta(seconds=60)), _hms(t1))
            if "path" in extra:
                evidence.append(extra["path"])
        return result("escalate", "high", f"{KIND_LABELS.get(kind, kind)} in {cam['zone']} at {_hms(t0)} "
                      "with no badge swipe in the last 10 minutes and no roster entry. "
                      "Clips from neighbouring cameras attached.")

    return result("escalate", "medium", f"Unrecognised event type '{kind}'; passed to a person.")
