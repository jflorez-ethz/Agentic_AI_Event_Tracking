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

from datetime import datetime
from typing import Any, Callable

from .context import SiteContext
from .recorder import NotYetAvailable, Recorder


class AgentTools:
    def __init__(self, recorder: Recorder, context: SiteContext):
        self.recorder = recorder
        self.context = context
        self.site = recorder.site
        self.trace: list[dict] = []

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
        """Ask the video model a question about a clip. Not wired yet: task C3 connects Gemini here."""
        def go():
            raise ValueError("ask_video is not connected yet (task C3).")
        return self._call("ask_video", {"clip_path": clip_path, "question": question}, go)

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
