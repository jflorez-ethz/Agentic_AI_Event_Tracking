"""The functions an agent may call. This is the only way an agent touches the site.

Each tool:
- takes and returns plain strings, numbers, lists and dicts, so any agent framework
  (Pydantic AI, LangGraph, an MCP server) can wrap it as it stands;
- checks the replay clock through the recorder, so footage and logs after "now" come
  back as an error message the agent can read, not as data;
- is logged to self.trace, which the screen shows as the agent's steps.

Times are site clock times: "02:10", "02:10:05" or an ISO timestamp.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from .context import SiteContext
from .recorder import NotYetAvailable, Recorder


SECOND_LOOK_HALF_S = 15  # second_look covers 15 s either side of the given time


class AgentTools:
    def __init__(self, recorder: Recorder, context: SiteContext, video_checker=None):
        self.recorder = recorder
        self.context = context
        self.site = recorder.site
        self.trace: list[dict] = []
        # Anything with check(clip_path, question="", *, strong=False) -> dict, for example
        # agentlab.video_check.VideoChecker. The triage agent sets one per alert.
        self.video_checker = video_checker

    def _call(self, name: str, args: dict, fn: Callable[[], Any]) -> Any:
        at = self.recorder.clock.now().strftime("%H:%M:%S")
        try:
            result = fn()
            self.trace.append({"site_time": at, "tool": name, "args": args, "ok": True, "result": _short(result)})
            return result
        except (NotYetAvailable, ValueError) as err:
            self.trace.append({"site_time": at, "tool": name, "args": args, "ok": False, "result": str(err)})
            return {"error": str(err)}

    def _t(self, value: str | datetime) -> datetime:
        return self.site.parse_time(value)

    # tools --------------------------------------------------------------------
    def now(self) -> dict:
        """Current site time on the replay clock."""
        return self._call("now", {}, lambda: {"site_time": self.recorder.clock.now().isoformat(timespec="seconds")})

    def list_cameras(self) -> list[dict]:
        """Cameras on the site with their zone, the doors they cover and their neighbouring cameras."""
        return self._call("list_cameras", {}, lambda: [
            {"id": c.id, "zone": c.zone, "doors": list(c.doors), "neighbors": list(c.neighbors)}
            for c in self.site.cameras
        ])

    def get_clip(self, camera_id: str, start: str, end: str) -> dict:
        """Cut a clip from one camera's recording between two site times (at most 10 minutes)."""
        def go():
            path = self.recorder.cut_clip(camera_id, self._t(start), self._t(end))
            return {"camera_id": camera_id, "start": str(start), "end": str(end), "path": str(path)}
        return self._call("get_clip", {"camera_id": camera_id, "start": str(start), "end": str(end)}, go)

    def get_frame(self, camera_id: str, at: str) -> dict:
        """Save one still frame from a camera at a site time and return its path."""
        def go():
            return {"camera_id": camera_id, "at": str(at), "path": str(self.recorder.save_frame(camera_id, self._t(at)))}
        return self._call("get_frame", {"camera_id": camera_id, "at": str(at)}, go)

    def access_log(self, start: str, end: str, door: str | None = None) -> dict:
        """Badge swipes between two site times, optionally for one door."""
        return self._call("access_log", {"start": str(start), "end": str(end), "door": door},
                          lambda: {"rows": self.context.access_log(self._t(start), self._t(end), door)})

    def roster(self, at: str) -> dict:
        """Who is scheduled to be on site at a site time (shifts, contractors, deliveries)."""
        return self._call("roster", {"at": str(at)}, lambda: {"rows": self.context.roster(self._t(at))})

    def procedures(self) -> dict:
        """The site's written procedures for after-hours activity, safety events and escalation."""
        return self._call("procedures", {}, lambda: {"text": self.context.procedures()})

    def ask_video(self, clip_path: str, question: str) -> dict:
        """Ask the video model about a clip cut with get_clip (pass the clip's path).

        It looks at 16 frames spread evenly over the clip and returns the events it sees, each with
        a type, whether it looks real or like a look-alike, and its times in seconds from the start
        of the clip. Clips must be 120 s or shorter. Put your specific question in `question`.
        """
        def go():
            if self.video_checker is None:
                raise ValueError("ask_video is not connected yet (task C3).")
            return self.video_checker.check(clip_path, question)
        return self._call("ask_video", {"clip_path": clip_path, "question": question}, go)

    def second_look(self, camera_id: str, around: str, question: str) -> dict:
        """Have the stronger video model look again at one camera, from 15 s before to 15 s after a
        site time (never later than now). Use it only when the evidence conflicts, for example the
        video shows no one but nobody badged in. At most twice per alert.
        """
        def go():
            if self.video_checker is None:
                raise ValueError("second_look is not connected (no video checker).")
            cam = self.site.camera(camera_id)
            t = self._t(around)
            now = self.recorder.clock.now()
            half = timedelta(seconds=SECOND_LOOK_HALF_S)
            start, end = max(t - half, cam.start), min(t + half, now)
            if end <= start:
                raise NotYetAvailable(f"Nothing has been recorded around {around} yet (now {now:%H:%M:%S}).")
            path = self.recorder.cut_clip(cam.id, start, end)
            result = self.video_checker.check(str(path), question, strong=True)
            return {**result, "camera_id": cam.id, "start": f"{start:%H:%M:%S}", "end": f"{end:%H:%M:%S}",
                    "clip_path": str(path)}
        return self._call("second_look", {"camera_id": camera_id, "around": str(around), "question": question}, go)

    def search_footage(self, query: str, start: str, end: str) -> dict:
        """Search all cameras for a described moment. Not wired yet: task C4 connects the search index here."""
        def go():
            self.recorder.check_recorded(self._t(end))
            raise ValueError("search_footage is not connected yet (task C4).")
        return self._call("search_footage", {"query": query, "start": str(start), "end": str(end)}, go)


def _short(result: Any) -> Any:
    """Keep the trace readable on screen."""
    if isinstance(result, dict) and "text" in result and len(result["text"]) > 160:
        return {**result, "text": result["text"][:160] + " ..."}
    if isinstance(result, dict) and isinstance(result.get("rows"), list):
        return {"rows": result["rows"][:5], "count": len(result["rows"])}
    return result
