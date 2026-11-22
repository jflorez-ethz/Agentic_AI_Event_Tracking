"""The fake recorder: cuts clips and frames out of the per-camera files.

This plays the part of the NVR on a real site. The one rule that makes the replay honest:
nothing after the replay clock's "now" can be read, because on a real site it would not
have been recorded yet.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from .clock import ReplayClock
from .media import run
from .site import Camera, Site

MAX_CLIP_S = 600  # keeps an agent from asking a video model to watch an hour by mistake


class NotYetAvailable(Exception):
    """Raised when a tool asks for footage or log entries after the replay clock."""


class Recorder:
    def __init__(self, site: Site, clock: ReplayClock, cache_dir: str | Path):
        self.site = site
        self.clock = clock
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._captures: dict[str, cv2.VideoCapture] = {}
        self._lock = threading.Lock()

    # the guard ----------------------------------------------------------------
    def check_recorded(self, until: datetime) -> None:
        now = self.clock.now()
        if until > now + timedelta(seconds=0.5):
            raise NotYetAvailable(
                f"Nothing after {now:%H:%M:%S} has been recorded yet (asked up to {until:%H:%M:%S}). "
                "Ask for an earlier window or wait."
            )

    # clips --------------------------------------------------------------------
    def cut_clip(self, camera_id: str, start: datetime, end: datetime) -> Path:
        cam = self.site.camera(camera_id)
        if end <= start:
            raise ValueError("The end of the window must be after its start.")
        if (end - start).total_seconds() > MAX_CLIP_S:
            raise ValueError(f"Windows are limited to {MAX_CLIP_S // 60} minutes. Ask for a shorter one.")
        self.check_recorded(end)
        s, e = max(start, cam.start), min(end, cam.end)
        if e <= s:
            raise ValueError(f"{cam.id} has no recording between {start:%H:%M:%S} and {end:%H:%M:%S}.")
        out = self.cache_dir / f"{cam.id}_{s:%Y%m%d-%H%M%S}_{e:%H%M%S}.mp4"
        if not out.exists():
            offset = (s - cam.start).total_seconds()
            run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{offset:.3f}", "-i", str(cam.path), "-t", f"{(e - s).total_seconds():.3f}",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
            ])
        return out

    # frames -------------------------------------------------------------------
    def frame(self, camera_id: str, at: datetime):
        """RGB frame (numpy array) of one camera at one site time, or None if there is none."""
        cam = self.site.camera(camera_id)
        self.check_recorded(at)
        return self._read_frame(cam, at)

    def save_frame(self, camera_id: str, at: datetime) -> Path:
        image = self.frame(camera_id, at)
        if image is None:
            raise ValueError(f"{camera_id} has no frame at {at:%H:%M:%S}.")
        out = self.cache_dir / f"{camera_id}_{at:%Y%m%d-%H%M%S}.jpg"
        cv2.imwrite(str(out), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        return out

    def _read_frame(self, cam: Camera, at: datetime):
        offset = (at - cam.start).total_seconds()
        if offset < 0 or offset > cam.duration_s:
            return None
        index = min(int(offset * cam.fps), max(int(cam.duration_s * cam.fps) - 1, 0))
        with self._lock:
            cap = self._captures.get(cam.id)
            if cap is None:
                cap = cv2.VideoCapture(str(cam.path))
                self._captures[cam.id] = cap
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ok else None
