"""Tests for agentlab/video_check.py: the frame check behind ask_video and second_look.
Fake Anthropic client, no API calls:  python -m pytest tests/test_video_check.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentlab import event_check, usage  # noqa: E402
from agentlab.video_check import VideoChecker, escalation_reason  # noqa: E402

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
FALL = {"event_type": "person_down", "start_s": 1.0, "end_s": 3.0, "real": True, "reason": "falls, stays down"}
BAG = {"event_type": "unattended_object", "start_s": 0.5, "end_s": 4.0, "real": True, "reason": "bag left"}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(event_check, "FRAMES_DIR", tmp_path / "frames")


def _clip(tmp_path: Path, seconds: int = 4, name: str = "clip.mp4") -> Path:
    p = tmp_path / name
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=size=160x120:rate=5:duration={seconds}", "-pix_fmt", "yuv420p", str(p)], check=True)
    return p


class FakeClient:
    """messages.create returns a canned answer per model and records the calls."""

    def __init__(self, answers: dict[str, list[dict]], fail: Exception | None = None):
        self.answers = answers
        self.fail = fail
        self.models: list[str] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        if self.fail:
            raise self.fail
        self.models.append(kw["model"])
        body = {"scene": "test pattern", "video_visible": True, "events": self.answers.get(kw["model"], [])}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(body))],
                               usage=SimpleNamespace(input_tokens=5000, output_tokens=300))


def test_escalation_reason_rules():
    assert escalation_reason("unattended_object", [BAG]) == "unattended object alert"
    assert escalation_reason("person_down", [FALL, BAG]) == "answer mentions an unattended object"
    assert escalation_reason("person_down", []) == "no person_down event in the answer"
    assert escalation_reason("person_down", [{**FALL, "real": False}]) is None  # a look-alike counts
    assert escalation_reason("person_down", [FALL]) is None


def test_keeps_haiku_answer_when_it_covers_the_alert(tmp_path):
    client = FakeClient({HAIKU: [FALL]})
    vc = VideoChecker(client, "person_down", tag="t")
    r = vc.check(str(_clip(tmp_path)), "is anyone down?")
    assert vc.calls == 1 and r["model"] == HAIKU and r["escalated"] is False and r["why"] is None
    assert r["events"][0]["event_type"] == "person_down"
    assert r["times"] == "seconds from the start of the clip"
    assert set(r) == {"scene", "video_visible", "events", "times", "model", "escalated", "why"}


def test_escalates_to_sonnet_when_nothing_of_the_kind(tmp_path):
    client = FakeClient({HAIKU: [], SONNET: [FALL]})
    vc = VideoChecker(client, "person_down")
    r = vc.check(str(_clip(tmp_path)))
    assert vc.calls == 2 and client.models == [HAIKU, SONNET]
    assert r["model"] == SONNET and r["escalated"] is True and r["why"] == "no person_down event in the answer"
    assert vc.ask_escalated is True


def test_unattended_object_always_escalates(tmp_path):
    client = FakeClient({HAIKU: [BAG], SONNET: [BAG]})
    vc = VideoChecker(client, "unattended_object")
    r = vc.check(str(_clip(tmp_path)))
    assert vc.calls == 2 and r["why"] == "unattended object alert"


def test_strong_goes_straight_to_sonnet(tmp_path):
    client = FakeClient({SONNET: [FALL]})
    vc = VideoChecker(client, "person_down")
    r = vc.check(str(_clip(tmp_path)), "q", strong=True)
    assert vc.calls == 1 and client.models == [SONNET]
    assert r["model"] == SONNET and r["escalated"] is True and r["why"] == "second look"
    assert vc.ask_escalated is False  # a second look is not an ask_video escalation


def test_cost_accumulates_from_usage_rows(tmp_path):
    vc = VideoChecker(FakeClient({HAIKU: [FALL]}), "person_down", tag="triage:X")
    vc.check(str(_clip(tmp_path)))
    assert vc.cost_usd > 0
    rows = [json.loads(line) for line in usage.USAGE_LOG.read_text().splitlines()]
    assert rows[0]["tag"] == f"triage:X:{HAIKU}"


def test_missing_clip_and_long_clip_raise_value_error(tmp_path):
    vc = VideoChecker(FakeClient({}), "person_down")
    with pytest.raises(ValueError, match="No clip at"):
        vc.check(str(tmp_path / "nope.mp4"))
    long_clip = _clip(tmp_path, 70, "long.mp4")
    with pytest.raises(ValueError, match=r"Clip is 70 s; frame checks need 60 s or less"):
        vc.check(str(long_clip))
    assert vc.calls == 0


def test_fifty_second_clip_is_accepted(tmp_path):
    """The usual unattended-object window (20 s before first seen to now, 30 s detector delay)."""
    vc = VideoChecker(FakeClient({SONNET: [BAG]}), "unattended_object")
    r = vc.check(str(_clip(tmp_path, 50, "fifty.mp4")))
    assert r["model"] == SONNET and vc.calls == 2


def test_client_failure_becomes_value_error(tmp_path):
    vc = VideoChecker(FakeClient({}, fail=RuntimeError("overloaded")), "person_down")
    with pytest.raises(ValueError) as err:
        vc.check(str(_clip(tmp_path)))
    assert str(err.value).startswith("video model unavailable")
    assert "RuntimeError: overloaded" in str(err.value)
