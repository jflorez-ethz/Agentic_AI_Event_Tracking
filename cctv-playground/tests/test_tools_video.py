"""ask_video and second_look in AgentTools, with a fake video checker (no API calls).

    python -m pytest tests/test_tools_video.py -q
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cctv_playground.clock import ReplayClock  # noqa: E402
from cctv_playground.context import SiteContext  # noqa: E402
from cctv_playground.recorder import Recorder  # noqa: E402
from cctv_playground.site import load_site  # noqa: E402
from cctv_playground.tools import AgentTools  # noqa: E402


class FakeChecker:
    def __init__(self):
        self.seen: list[tuple[str, str, bool]] = []

    def check(self, clip_path: str, question: str = "", *, strong: bool = False) -> dict:
        if not Path(clip_path).is_file():
            raise ValueError(f"No clip at {clip_path}.")
        self.seen.append((clip_path, question, strong))
        return {"events": [], "model": "fake"}


@pytest.fixture
def tools(site_dir, tmp_path) -> AgentTools:
    site = load_site(site_dir / "site" / "index.json")
    clock = ReplayClock(site.start, site.end)
    clock.jump(site.start + timedelta(seconds=10))  # now = 02:00:10
    return AgentTools(Recorder(site, clock, tmp_path), SiteContext(site, clock))


def test_ask_video_without_checker_is_an_error(tools):
    out = tools.ask_video("/nowhere.mp4", "what happens?")
    assert "not connected yet" in out["error"]
    assert tools.trace[-1]["ok"] is False


def test_ask_video_calls_the_checker(tools):
    tools.video_checker = FakeChecker()
    clip = tools.get_clip("CAM-A", "02:00:02", "02:00:08")["path"]
    out = tools.ask_video(clip, "is anyone there?")
    assert out == {"events": [], "model": "fake"}
    assert tools.video_checker.seen == [(clip, "is anyone there?", False)]
    assert [(s["tool"], s["ok"]) for s in tools.trace] == [("get_clip", True), ("ask_video", True)]


def test_ask_video_missing_clip_is_an_error_in_the_trace(tools):
    tools.video_checker = FakeChecker()
    out = tools.ask_video("/no/such/clip.mp4", "q")
    assert out["error"].startswith("No clip at")
    assert tools.trace[-1]["tool"] == "ask_video" and tools.trace[-1]["ok"] is False


def test_unparseable_time_is_an_error(tools):
    out = tools.get_clip("CAM-A", "ten past two", "02:00:05")
    assert "Could not read the time" in out["error"]
    assert tools.trace[-1]["ok"] is False


def test_second_look_clamps_to_now(tools):
    checker = tools.video_checker = FakeChecker()
    out = tools.second_look("CAM-A", "02:00:09", "is anyone lying down?")
    assert out["end"] == "02:00:10"
    assert out["camera_id"] == "CAM-A" and Path(out["clip_path"]).is_file()
    assert checker.seen == [(out["clip_path"], "is anyone lying down?", True)]
    assert tools.trace[-1]["tool"] == "second_look" and tools.trace[-1]["ok"] is True


def test_second_look_in_the_future_is_refused(tools):
    tools.video_checker = FakeChecker()
    out = tools.second_look("CAM-A", "02:00:28", "q")
    assert "Nothing has been recorded around 02:00:28 yet (now 02:00:10)" in out["error"]
    assert tools.video_checker.seen == []


def test_second_look_without_checker_is_an_error(tools):
    out = tools.second_look("CAM-A", "02:00:05", "q")
    assert out["error"] == "second_look is not connected (no video checker)."


def test_ask_video_description_gives_the_60_s_limit():
    """The agent's tool description is this docstring."""
    doc = " ".join(AgentTools.ask_video.__doc__.split())
    assert "Clips must be 60 s or shorter" in doc
    assert "30 s, or 50 s for unattended objects" in doc
    assert "120" not in doc
