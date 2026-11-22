"""Stand-in detector, so the agents can be built before the real detector works.

It fires a candidate event a few seconds after each labelled event begins, look-alikes
included, which is what a person or vehicle detector with zones and schedules would do.
It never passes on whether the event is real: deciding that is the triage agent's job.

Task C1 replaces this with RF-DETR (or YOLO) running on the camera files up to "now".
Keep the same output: a list of candidate dicts.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .site import Site


# Seconds of footage the detector needs before it fires, by event type. An object only
# counts as unattended once it has been left for a while; everything else uses delay_s.
KIND_DELAYS = {"unattended_object": 30.0}


class OracleDetector:
    def __init__(self, site: Site, delay_s: float = 10.0, already_fired: set[str] | None = None,
                 kind_delays: dict[str, float] | None = None):
        self.site = site
        self.delay = timedelta(seconds=delay_s)  # the default, for types not in kind_delays
        self.kind_delays = dict(KIND_DELAYS if kind_delays is None else kind_delays)
        self.fired: set[str] = set(already_fired or ())

    def delay_for(self, kind: str) -> timedelta:
        if kind in self.kind_delays:
            return timedelta(seconds=self.kind_delays[kind])
        return self.delay

    def poll(self, now: datetime) -> list[dict]:
        """Candidates due by `now` and not fired yet, in the order they were detected."""
        out = []
        for label in sorted(self.site.labels, key=lambda l: (l.start + self.delay_for(l.type), l.start)):
            detected_at = label.start + self.delay_for(label.type)
            if label.id in self.fired or now < detected_at:
                continue
            self.fired.add(label.id)
            cam = self.site.camera(label.camera_id)
            out.append({
                "candidate_id": label.id,
                "camera_id": cam.id,
                "zone": cam.zone,
                "kind": label.type,
                "first_seen": label.start.isoformat(timespec="seconds"),
                "detected_at": detected_at.isoformat(timespec="seconds"),
            })
        return out
