"""The footage index: which file holds which camera, from which site time.

build_site.py writes site/index.json; everything else reads it through load_site().
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class Camera:
    id: str
    zone: str
    path: Path
    start: datetime          # site time of the first frame
    duration_s: float
    fps: float
    width: int
    height: int
    doors: tuple[str, ...] = ()
    neighbors: tuple[str, ...] = ()
    source: str = ""

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.duration_s)


@dataclass(frozen=True)
class Label:
    """Ground truth for one event. Used by the stand-in detector and for scoring only.

    Never pass labels (and above all `real`) to an agent tool: that would let the
    agent read the answer instead of working it out."""
    id: str
    camera_id: str
    type: str
    start: datetime
    end: datetime
    real: bool
    note: str = ""


@dataclass
class Site:
    name: str
    start: datetime
    duration_s: float
    cameras: list[Camera]
    labels: list[Label]
    context: dict[str, Path] = field(default_factory=dict)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.duration_s)

    def camera(self, camera_id: str) -> Camera:
        for cam in self.cameras:
            if cam.id.lower() == str(camera_id).strip().lower():
                return cam
        known = ", ".join(c.id for c in self.cameras)
        raise ValueError(f"Unknown camera '{camera_id}'. Cameras on this site: {known}.")

    def parse_time(self, value: str | datetime) -> datetime:
        """Accept a datetime, an ISO timestamp, or a site clock time such as '02:10' or '02:10:05'."""
        return parse_site_time(value, self.start, self.end)


def parse_site_time(value: str | datetime, site_start: datetime, site_end: datetime) -> datetime:
    """Read a time the way a guard would say it.

    A bare clock time ('22:00', '02:10:05') is put on the day before, the day of, or the
    day after the site start, whichever lands closest to the replayed window. So a roster
    shift from 22:00 to 03:00 around a 01:50 replay reads as last night to this morning."""
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            clock = datetime.strptime(text, fmt).time()
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Could not read the time '{value}'. Use HH:MM, HH:MM:SS or an ISO timestamp.")

    def distance(t: datetime) -> float:
        if site_start <= t <= site_end:
            return 0.0
        return min(abs((t - site_start).total_seconds()), abs((t - site_end).total_seconds()))

    options = [datetime.combine(site_start.date() + timedelta(days=d), clock) for d in (-1, 0, 1)]
    return min(options, key=distance)


def load_site(index_path: str | Path) -> Site:
    index_path = Path(index_path).resolve()
    if not index_path.exists():
        raise SystemExit(f"{index_path} not found. Run: python scripts/build_site.py site.yaml")
    data = json.loads(index_path.read_text())
    base = index_path.parent
    cameras = [
        Camera(
            id=c["id"], zone=c["zone"], path=(base / c["file"]).resolve(),
            start=datetime.fromisoformat(c["start"]), duration_s=c["duration_s"],
            fps=c["fps"], width=c["width"], height=c["height"],
            doors=tuple(c.get("doors", [])), neighbors=tuple(c.get("neighbors", [])),
            source=c.get("source", ""),
        )
        for c in data["cameras"]
    ]
    labels = [
        Label(
            id=l["id"], camera_id=l["camera_id"], type=l["type"],
            start=datetime.fromisoformat(l["start"]), end=datetime.fromisoformat(l["end"]),
            real=bool(l["real"]), note=l.get("note", ""),
        )
        for l in data.get("labels", [])
    ]
    context = {k: (base / v).resolve() for k, v in data.get("context", {}).items()}
    return Site(
        name=data["name"], start=datetime.fromisoformat(data["start"]),
        duration_s=data["duration_s"], cameras=cameras, labels=labels, context=context,
    )
