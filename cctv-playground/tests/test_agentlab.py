"""Tests for the step 4 code: prompt loading, parsing, scoring, API wrappers with fake clients.
No API calls and no keys needed:  python -m pytest tests/test_agentlab.py -q
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
from agentlab.scoring import score  # noqa: E402

ANSWER = {"scene": "small room with a desk", "video_visible": True, "events": [
    {"event_type": "person_down", "start_s": 5.0, "end_s": 12.0, "real": True, "reason": "falls and stays down"},
    {"event_type": "after_hours_person", "start_s": 0, "end_s": 9.5, "real": True, "reason": "walks in"},
    {"event_type": "fire", "start_s": 1, "end_s": 2, "real": True, "reason": "not a type"},
]}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(event_check, "_UPLOADS", tmp_path / "gemini_files.json")
    monkeypatch.setattr(event_check, "FRAMES_DIR", tmp_path / "frames")


def item(typ, real, start, end, dur=10):
    return {"type": typ, "real": real, "start_s": start, "end_s": end, "duration_s": dur}


def test_prompt_v2_sections():
    p = event_check.load_prompt("v2")
    assert {"SYSTEM", "USER", "FRAMES_NOTE", "schema"} <= set(p)
    assert "9.5 seconds" in p["USER"].format(duration=9.5)
    assert p["schema"]["properties"]["events"]["items"]["properties"]["event_type"]["enum"] == event_check.EVENT_TYPES


def test_parse_caps_times_and_drops_unknown_types():
    r = event_check.parse_result(json.dumps(ANSWER), duration=9.5)
    assert [e["event_type"] for e in r["events"]] == ["person_down", "after_hours_person"]
    assert r["events"][0]["end_s"] == 9.5


def test_score_real_hit_top1_and_start_error():
    r = event_check.parse_result(json.dumps(ANSWER), 9.5)
    s = score(item("person_down", "true", 6.0, 9.5), r)
    assert s["correct"] and s["top1"] and s["start_err"] == 1.0 and not s["missed_critical"]


def test_score_right_type_wrong_time_is_a_miss():
    r = {"events": [{"event_type": "unattended_object", "start_s": 8, "end_s": 12, "real": True, "reason": ""}]}
    s = score(item("unattended_object", "true", 27.0, 70.0, 70), r)
    assert not s["correct"] and s["type_only"]


def test_score_overlapping_but_early_start_is_a_miss():
    # smoke test: Hydrogen reported the decoy bag "8-70 s"; the label is 27-70 s
    r = {"events": [{"event_type": "unattended_object", "start_s": 8, "end_s": 70, "real": True, "reason": ""}]}
    assert not score(item("unattended_object", "true", 27.0, 70.0, 70), r)["correct"]
    r["events"][0]["start_s"] = 29
    assert score(item("unattended_object", "true", 27.0, 70.0, 70), r)["correct"]


def test_score_lookalike_alarm_vs_named():
    alarm = {"events": [{"event_type": "person_down", "start_s": 2, "end_s": 10, "real": True, "reason": ""}]}
    named = {"events": [{"event_type": "person_down", "start_s": 2, "end_s": 10, "real": False, "reason": ""}]}
    assert score(item("person_down", "false", 2.0, 10.95), alarm)["false_alarm"]
    s = score(item("person_down", "false", 2.0, 10.95), named)
    assert s["correct"] and s["recognised"]


def test_score_none_ignores_people_outside_zone():
    r = {"events": [{"event_type": "after_hours_person", "start_s": 0, "end_s": 50, "real": True, "reason": ""}]}
    s = score(item("none", "false", 0, 50, 50), r)
    assert s["correct"] and s["people_outside_zone"]
    r["events"].append({"event_type": "after_hours_vehicle", "start_s": 3, "end_s": 9, "real": True, "reason": ""})
    assert not score(item("none", "false", 0, 50, 50), r)["correct"]


def test_score_video_missing_counts_as_missed_fall():
    s = score(item("person_down", "true", 6.0, 9.5), {"events": ANSWER["events"], "video_missing": True})
    assert not s["correct"] and s["missed_critical"]


def _clip(tmp_path: Path, seconds: int = 4) -> Path:
    p = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    return p


class FakeGemini:
    def __init__(self, video_tokens):
        self.video_tokens = video_tokens
        f = SimpleNamespace(name="files/abc", uri="https://x/files/abc", mime_type="video/mp4",
                            state=SimpleNamespace(name="ACTIVE"))
        self.files = SimpleNamespace(upload=lambda file: f, get=lambda name: f)
        self.models = SimpleNamespace(generate_content=self._gen)
        self.config = None

    def _gen(self, model, contents, config):
        self.config = config
        details = [SimpleNamespace(modality=SimpleNamespace(value="TEXT"), token_count=1100),
                   SimpleNamespace(modality=SimpleNamespace(value="VIDEO"), token_count=self.video_tokens)]
        u = SimpleNamespace(prompt_token_count=1100 + self.video_tokens, candidates_token_count=120,
                            thoughts_token_count=300, prompt_tokens_details=details)
        return SimpleNamespace(text=json.dumps(ANSWER), usage_metadata=u)


def test_gemini_check_counts_video_tokens_and_logs(tmp_path):
    pytest.importorskip("google.genai")
    clip = _clip(tmp_path)
    fake = FakeGemini(video_tokens=280)
    r = event_check.gemini_check(fake, "gemini-3.8-flash", clip, 4.0, thinking="LOW", tag="t")
    assert not r["video_missing"] and r["video_tokens"] == 280
    assert r["usage"]["output_tokens"] == 420 and r["usage"]["cost_usd"] > 0
    assert str(fake.config.thinking_config.thinking_level.name) == "LOW"
    assert usage.USAGE_LOG.exists()
    r0 = event_check.gemini_check(FakeGemini(video_tokens=0), "gemini-3.8-flash", clip, 4.0)
    assert r0["video_missing"]


def test_claude_check_sends_frames_with_times(tmp_path):
    clip = _clip(tmp_path)
    sent = {}

    def create(**kw):
        sent.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(ANSWER))],
                               usage=SimpleNamespace(input_tokens=7000, output_tokens=500))

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    r = event_check.claude_check(fake, "claude-sonnet-5-5", clip, 4.0, n_frames=4)
    blocks = sent["messages"][0]["content"]
    assert sum(1 for b in blocks if b["type"] == "image") == 4
    assert blocks[0]["text"] == "Frame at 0.5 s:"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert r["usage"]["cost_usd"] == pytest.approx(0.019)


def test_summary_and_estimate():
    sys.path.insert(0, str(ROOT / "scripts"))
    import compare_models as cm
    items = [{"duration_s": "10"}, {"duration_s": "70"}]
    total, lines = cm.estimate(["g38-low", "sonnet-8f"], items, repeats=3)
    assert 0 < total < 1 and len(lines) == 2
    call = {"variant": "g38-low", "item": "T01", "error": None, "seconds": 5.0, "video_missing": False,
            "label": {"type": "person_down", "real": "true"}, "cost_2027": 0.003,
            "usage": {"input_tokens": 1200, "output_tokens": 200, "cost_usd": 0.0017},
            "score": {"correct": True, "top1": True, "start_err": 1.0, "type_only": False, "recognised": False,
                      "false_alarm": False, "missed_critical": False}}
    rows, md = cm.summarise([call, {**call, "item": "T02", "error": "boom", "score": None}], ["g38-low"])
    assert rows[0]["correct_%"] == 100 and rows[0]["errors"] == 1 and "1/1" in md
