"""Site context on the same clock: access log, roster and procedures.

The access log follows the same rule as the footage: entries after "now" do not exist yet.
The roster is a plan, so it can be read for any time.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .clock import ReplayClock
from .recorder import NotYetAvailable
from .site import Site


def _read_csv(path: Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


class SiteContext:
    def __init__(self, site: Site, clock: ReplayClock):
        self.site = site
        self.clock = clock
        self._access = [
            {**row, "_t": site.parse_time(row["time"])} for row in _read_csv(site.context.get("access_log"))
        ]
        self._roster = [
            {**row, "_start": site.parse_time(row["start"]), "_end": site.parse_time(row["end"])}
            for row in _read_csv(site.context.get("roster"))
        ]
        proc = site.context.get("procedures")
        self._procedures = Path(proc).read_text(encoding="utf-8") if proc and Path(proc).exists() else ""

    def access_log(self, start: datetime, end: datetime, door: str | None = None) -> list[dict]:
        now = self.clock.now()
        if end > now:
            raise NotYetAvailable(f"The access log only runs to {now:%H:%M:%S}; asked up to {end:%H:%M:%S}.")
        rows = [r for r in self._access if start <= r["_t"] <= end]
        if door:
            rows = [r for r in rows if r.get("door", "").lower() == door.lower()]
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

    def roster(self, at: datetime) -> list[dict]:
        rows = [r for r in self._roster if r["_start"] <= at <= r["_end"]]
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

    def procedures(self) -> str:
        return self._procedures
