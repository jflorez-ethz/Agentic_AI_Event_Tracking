"""The replay clock: one site time shared by the screen, the detector and the agent tools.

site time = anchor_site + (wall clock now - anchor_wall) * speed, unless paused.

With a path, the state lives in a small JSON file so separate processes (the Streamlit
screen and run_replay.py) agree on "now". Without a path it lives in memory, which is
what evaluate.py uses to jump straight from one event to the next.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path


class ReplayClock:
    def __init__(self, site_start: datetime, site_end: datetime, path: str | Path | None = None):
        self.site_start = site_start
        self.site_end = site_end
        self.path = Path(path) if path else None
        self._state: dict | None = self._read() if self.path else None
        if self._state is None:
            self._state = self._fresh(site_start)
            self._write()

    # state handling -----------------------------------------------------------
    @staticmethod
    def _fresh(site_time: datetime) -> dict:
        return {"anchor_site": site_time.isoformat(), "anchor_wall": time.time(), "speed": 1.0, "paused": True}

    def _read(self) -> dict | None:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError, AttributeError):
            return None

    def _write(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._state))
        os.replace(tmp, self.path)  # atomic, so a reader never sees half a file

    def _sync(self) -> None:
        if self.path:
            state = self._read()
            if state:
                self._state = state

    def _clamp(self, t: datetime) -> datetime:
        return min(max(t, self.site_start), self.site_end)

    def _reanchor(self, site_time: datetime, *, speed: float | None = None, paused: bool | None = None) -> None:
        self._sync()
        self._state = {
            "anchor_site": self._clamp(site_time).isoformat(),
            "anchor_wall": time.time(),
            "speed": self._state["speed"] if speed is None else float(speed),
            "paused": self._state["paused"] if paused is None else bool(paused),
        }
        self._write()

    # public API ---------------------------------------------------------------
    def now(self) -> datetime:
        self._sync()
        s = self._state
        t = datetime.fromisoformat(s["anchor_site"])
        if not s["paused"]:
            t += timedelta(seconds=(time.time() - s["anchor_wall"]) * s["speed"])
        return self._clamp(t)

    @property
    def paused(self) -> bool:
        self._sync()
        return bool(self._state["paused"])

    @property
    def speed(self) -> float:
        self._sync()
        return float(self._state["speed"])

    def play(self) -> None:
        self._reanchor(self.now(), paused=False)

    def pause(self) -> None:
        self._reanchor(self.now(), paused=True)

    def set_speed(self, speed: float) -> None:
        self._reanchor(self.now(), speed=speed)

    def jump(self, site_time: datetime) -> None:
        self._reanchor(site_time)

    def reset(self) -> None:
        self._sync()
        self._state = self._fresh(self.site_start)
        self._write()
