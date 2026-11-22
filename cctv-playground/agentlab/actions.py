"""Proposed actions by event type (task D3). They mirror the site procedures (context/procedures.md).

Only proposals: approving one in review.py logs a simulated dispatch, and nothing here contacts anyone.
"""
from __future__ import annotations

NEAREST_GUARD = "Send the nearest guard to {zone} now. The guard decides whether to call emergency services."
GUARD_ON_DUTY = "The guard on duty checks {zone} and decides on dispatch. The system never contacts the police."
ACTIONS = {
    "person_down": NEAREST_GUARD,
    "fire": NEAREST_GUARD,
    "after_hours_person": GUARD_ON_DUTY,
    "after_hours_vehicle": GUARD_ON_DUTY,
    "unattended_object": "A guard checks the object in {zone} in person. It is not moved before it is checked.",
    "blocked_exit": "The supervisor has the exit in {zone} cleared before the next shift.",
}
DEFAULT_ACTION = "The guard on duty reviews the clip."


def proposed_action(kind: str, zone: str) -> str:
    return ACTIONS.get(kind, DEFAULT_ACTION).format(zone=zone)
