"""The step 5 triage agent with scripted models (Pydantic AI FunctionModel). No API calls.

    python -m pytest tests/test_triage_agent.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydantic_ai import ModelResponse, ToolCallPart, ToolReturnPart, models  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from agentlab.triage_agent import (  # noqa: E402
    INSTRUCTIONS, AgentTriage, TriageVerdict, apply_rules, build_agent, evidence_from_trace, first_video_answer,
    task_message,
)
from fakecctv.clock import ReplayClock  # noqa: E402
from fakecctv.context import SiteContext  # noqa: E402
from fakecctv.recorder import Recorder  # noqa: E402
from fakecctv.site import load_site  # noqa: E402
from fakecctv.tools import AgentTools  # noqa: E402

models.ALLOW_MODEL_REQUESTS = False  # a test that reaches a real model fails instead of paying

KEYS = {"verdict", "priority", "reason", "evidence", "linked_to"}
CANDIDATE = {"candidate_id": "CAM-B-1", "camera_id": "CAM-B", "zone": "Dock", "kind": "after_hours_person",
             "first_seen": "2026-01-10T02:00:12", "detected_at": "2026-01-10T02:00:14"}


class FakeChecker:
    def __init__(self, ask_escalated: bool = False, events: list[dict] | None = None):
        self.events = events or []
        self.seen: list[tuple[str, str, bool]] = []
        self.calls = 0
        self.cost_usd = 0.0
        self.ask_escalated = ask_escalated

    def check(self, clip_path: str, question: str = "", *, strong: bool = False) -> dict:
        if not Path(clip_path).is_file():
            raise ValueError(f"No clip at {clip_path}.")
        self.seen.append((clip_path, question, strong))
        self.calls += 1
        self.cost_usd += 0.001
        return {"scene": "test", "video_visible": True, "events": list(self.events),
                "times": "seconds from the start of the clip",
                "model": "fake", "escalated": strong, "why": "second look" if strong else None}


def alert(aid: str, camera: str, kind: str = "after_hours_person", priority: str = "high") -> dict:
    return {"id": aid, "priority": priority, "verdict": "escalate",
            "candidate": {"camera_id": camera, "kind": kind, "first_seen": "2026-01-10T02:00:05"}}


@pytest.fixture
def tools(site_dir, tmp_path) -> AgentTools:
    site = load_site(site_dir / "site" / "index.json")
    clock = ReplayClock(site.start, site.end)
    clock.jump(site.start + timedelta(seconds=14))  # now = 02:00:14
    return AgentTools(Recorder(site, clock, tmp_path / "clips"), SiteContext(site, clock))


def scripted(*steps):
    """A FunctionModel that plays one step per model request. A step is (tool_name, args) or a
    function (messages, info) -> (tool_name, args); the tool name "OUTPUT" means the output tool."""
    def fn(messages, info: AgentInfo) -> ModelResponse:
        i = sum(1 for m in messages if isinstance(m, ModelResponse))
        step = steps[min(i, len(steps) - 1)]
        name, args = step(messages, info) if callable(step) else step
        if name == "OUTPUT":
            assert info.output_tools, "expected a tool-based output"
            name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(name, args)])
    return FunctionModel(fn)


def returns(messages) -> list[ToolReturnPart]:
    return [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]


def run_scripted(triage: AgentTriage, model: FunctionModel, tools: AgentTools, open_alerts=None) -> dict:
    with triage.agent.override(model=model):
        return triage(CANDIDATE, tools, open_alerts or [])


# --- the rules applied in code ------------------------------------------------------------
def test_apply_rules_safety_override():
    cand = {**CANDIDATE, "kind": "person_down"}
    out = TriageVerdict(verdict="dismiss", priority="low", reason="Person kneels to tie a shoe, gets up.")
    final, overrides = apply_rules(cand, out, None, [], [], [])
    assert final["verdict"] == "escalate" and final["priority"] == "high"
    assert "[Rule: person-down and fire alerts always go to a person, priority high.]" in final["reason"]
    assert final["reason"].startswith("Person kneels")
    assert overrides == ["safety rule"]
    assert set(final) == KEYS


def test_apply_rules_bad_link_and_good_link():
    out = TriageVerdict(verdict="linked", priority="medium", reason="Same person as on CAM-A.", linked_to="A-009")
    open_alerts = [alert("A-001", "CAM-A"), alert("A-002", "CAM-Z")]
    final, overrides = apply_rules(CANDIDATE, out, None, open_alerts, ["CAM-A"], [])
    assert final["verdict"] == "escalate" and final["priority"] == "medium" and final["linked_to"] is None
    assert "[Rule: link target is not an open alert on a neighbouring camera; sent to a person.]" in final["reason"]
    assert overrides == ["bad link"]
    # an open alert, but not on a neighbouring camera
    final, _ = apply_rules(CANDIDATE, out.model_copy(update={"linked_to": "A-002"}), None, open_alerts, ["CAM-A"], [])
    assert final["verdict"] == "escalate"
    final, overrides = apply_rules(CANDIDATE, out.model_copy(update={"linked_to": "A-001"}), None,
                                   open_alerts, ["CAM-A"], [])
    assert final["verdict"] == "linked" and final["linked_to"] == "A-001" and overrides == []


def test_apply_rules_failure():
    final, overrides = apply_rules(CANDIDATE, None, "UsageLimitExceeded: too many requests", [], [], [])
    assert final["verdict"] == "escalate" and final["priority"] == "medium"
    assert final["reason"].startswith("Agent could not finish")
    assert overrides == ["failure"] and set(final) == KEYS
    # a failed person-down check still goes out at high priority
    final, overrides = apply_rules({**CANDIDATE, "kind": "person_down"}, None, "boom", [], [], [])
    assert final["priority"] == "high" and overrides == ["failure", "safety rule"]


def test_apply_rules_linked_to_cleared_unless_linked():
    out = TriageVerdict(verdict="escalate", priority="high", reason="A person climbs the fence.", linked_to="A-001")
    final, _ = apply_rules(CANDIDATE, out, None, [alert("A-001", "CAM-A")], ["CAM-A"], [])
    assert final["linked_to"] is None


def test_evidence_from_trace_only_successful_paths():
    trace = [
        {"tool": "get_clip", "ok": False, "result": "Nothing after ..."},
        {"tool": "get_clip", "ok": True, "result": {"path": "/c/1.mp4"}},
        {"tool": "ask_video", "ok": True, "result": {"events": []}},
        {"tool": "get_frame", "ok": True, "result": {"path": "/c/f.jpg"}},
        {"tool": "get_clip", "ok": True, "result": {"path": "/c/1.mp4"}},
        {"tool": "second_look", "ok": True, "result": {"clip_path": "/c/2.mp4", "events": []}},
        {"tool": "second_look", "ok": False, "result": "Second-look limit (2) reached for this alert."},
    ]
    assert evidence_from_trace(trace) == ["/c/1.mp4", "/c/f.jpg", "/c/2.mp4"]


def _ev(kind: str, real: bool) -> dict:
    return {"event_type": kind, "start_s": 1.0, "end_s": 2.0, "real": real, "reason": "test"}


def _clip_step(camera: str, path: str, ok: bool = True) -> dict:
    return {"tool": "get_clip", "ok": ok, "args": {"camera_id": camera, "start": "02:00:00", "end": "02:00:14"},
            "result": {"camera_id": camera, "path": path} if ok else "error"}


def _ask_step(path: str, events: list[dict] | None, ok: bool = True) -> dict:
    return {"tool": "ask_video", "ok": ok, "args": {"clip_path": path, "question": "q"},
            "result": {"events": events, "model": "fake"} if ok else "video model unavailable"}


def test_first_video_answer():
    kind = "after_hours_person"
    own, other = "/c/CAM-B_1.mp4", "/c/CAM-A_1.mp4"
    base = [_clip_step("CAM-A", other), _clip_step("CAM-B", own)]
    # a neighbour's ask comes first and an own-camera ask errors: both skipped
    trace = base + [_ask_step(other, [_ev(kind, True)]), _ask_step(own, None, ok=False),
                    _ask_step(own, [_ev(kind, False), _ev("after_hours_vehicle", True)]),
                    _ask_step(own, [_ev(kind, True)])]
    assert first_video_answer(trace, "CAM-B", kind) == "look-alike"
    assert first_video_answer(base + [_ask_step(own, [_ev(kind, False), _ev(kind, True)])], "CAM-B", kind) == "real"
    assert first_video_answer(base + [_ask_step(own, [_ev("person_down", True)])], "CAM-B", kind) == "none"
    assert first_video_answer(base + [_ask_step(other, [_ev(kind, True)])], "CAM-B", kind) is None
    assert first_video_answer([], "CAM-B", kind) is None
    # a second look is not an ask_video answer
    look = {"tool": "second_look", "ok": True, "args": {"camera_id": "CAM-B"},
            "result": {"clip_path": own, "events": [_ev(kind, True)]}}
    assert first_video_answer(base + [look], "CAM-B", kind) is None


def test_task_message_without_doors_or_neighbours(tools):
    cam = tools.site.camera("CAM-B")
    msg = task_message(CANDIDATE, "02:00:14", cam, [alert("A-001", "CAM-A")])
    assert "CAM-B-1" in msg and "CAM-B" in msg and "Dock" in msg and "after_hours_person" in msg
    assert "02:00:12" in msg and "02:00:14" in msg
    assert "none" in msg
    assert "No open alerts on neighbouring cameras." in msg  # CAM-A is not a neighbour of CAM-B
    assert "real" not in msg.lower()


def test_task_message_lists_open_alerts_on_neighbours(tools):
    cam = tools.site.camera("CAM-A")
    cand = {**CANDIDATE, "candidate_id": "CAM-A-1", "camera_id": "CAM-A", "zone": "Yard"}
    msg = task_message(cand, "02:00:14", cam, [alert("A-007", "CAM-B")])
    assert "Door 1" in msg
    # the test site has no neighbours, so pass a camera-like object that has one
    fake_cam = type("C", (), {"id": "CAM-A", "zone": "Yard", "doors": ("Door 1",), "neighbors": ("CAM-B",)})()
    msg = task_message(cand, "02:00:14", fake_cam, [alert("A-007", "CAM-B")])
    assert "A-007" in msg and "CAM-B" in msg and "priority high" in msg


def test_task_message_shows_the_start_of_each_neighbour_reason():
    """So the agent can compare what was seen before linking (run 2 linked a white car to a red pickup)."""
    cand = {**CANDIDATE, "candidate_id": "CAM-A-1", "camera_id": "CAM-A", "zone": "Yard"}
    fake_cam = type("C", (), {"id": "CAM-A", "zone": "Yard", "doors": (), "neighbors": ("CAM-B",)})()
    reason = "A red pickup drives in\nfrom the gate. " + "x" * 160 + "TAIL-AFTER-200" + "y" * 100
    assert len(reason) > 200
    msg = task_message(cand, "02:00:14", fake_cam, [{**alert("A-007", "CAM-B"), "reason": reason}])
    line = next(l for l in msg.splitlines() if "A-007" in l)
    assert "A red pickup drives in from the gate. " in line  # newlines folded into the one line
    assert " ".join(reason.split())[:200] in line
    assert "TAIL-AFTER-200" not in msg
    short = task_message(cand, "02:00:14", fake_cam, [{**alert("A-007", "CAM-B"), "reason": "A white SUV."}])
    assert 'reason: "A white SUV."' in short


def test_instructions_link_only_on_matching_description():
    text = _flat(INSTRUCTIONS)
    assert ("Link only when the neighbouring alert's reason describes the same kind of vehicle or person "
            "(type and colour match) and the timing fits. If the description differs or is unclear, "
            "escalate instead of linking.") in text


def test_instructions_reason_never_mentions_gender_age_or_ethnicity():
    """Run 2's bag alert said "a woman in a blue jacket", copied from the video check."""
    text = _flat(INSTRUCTIONS)
    assert ("The reason never mentions gender, age or ethnicity, even when ask_video's answer does; "
            'write "a person".') in text


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_instructions_open_with_the_roster_exception():
    assert _flat(INSTRUCTIONS).startswith(
        "You are the triage step in the control room of an industrial or logistics site. "
        "The site is closed, except for the people and zones the roster lists.")


def test_instructions_keep_clips_short():
    """Run 2 cut a 90 s first clip (CAM-04-6) and 53 s and 105 s neighbour clips."""
    text = _flat(INSTRUCTIONS)
    assert "The first clip runs from 20 s before first seen to now." in text
    assert "For more context, look at a neighbouring camera, not a longer clip." in text
    assert ("A neighbouring camera's clip is 60 s or less, centred on the neighbouring alert's "
            "first-seen time") in text


def test_no_sampling_settings():
    # claude-haiku-5-5 rejects non-default temperature, top_p and top_k
    settings = build_agent().model_settings or {}
    assert not {"temperature", "top_p", "top_k"} & set(settings)


# --- the agent with scripted models ---------------------------------------------------------
def test_agent_recovers_from_future_clip(tools):
    checker = FakeChecker()
    triage = AgentTriage(checker_factory=lambda kind, tag: checker)

    def ask(messages, info):
        clip = returns(messages)[-1].content["path"]
        return "ask_video", {"clip_path": clip, "question": "what happens"}

    model = scripted(
        ("get_clip", {"camera_id": "CAM-B", "start": "02:00:00", "end": "02:00:25"}),  # after now: refused
        ("get_clip", {"camera_id": "CAM-B", "start": "02:00:00", "end": "02:00:14"}),
        ask,
        ("OUTPUT", {"verdict": "escalate", "priority": "high",
                    "reason": "A person walks onto the dock at 02:00:12 with no badge or roster entry."}),
    )
    final = run_scripted(triage, model, tools)
    assert [s["ok"] for s in tools.trace] == [False, True, True]
    clip = tools.trace[1]["result"]["path"]
    assert final["evidence"] == [clip]
    assert final["verdict"] == "escalate" and final["priority"] == "high"
    assert set(final) == KEYS
    stats = triage.stats["CAM-B-1"]
    assert stats["tool_errors"] == 1 and stats["tool_calls"] == 3 and stats["requests"] == 4
    assert stats["video_calls"] == 1 and stats["overrides"] == []
    assert stats["cost_usd"] > 0
    assert checker.seen == [(clip, "what happens", False)]
    assert tools.video_checker is checker


def test_stats_record_the_first_video_answer(tools):
    checker = FakeChecker(events=[_ev("after_hours_person", False)])
    triage = AgentTriage(checker_factory=lambda kind, tag: checker)

    def ask(messages, info):
        return "ask_video", {"clip_path": returns(messages)[-1].content["path"], "question": "anyone?"}

    model = scripted(("get_clip", {"camera_id": "CAM-B", "start": "02:00:00", "end": "02:00:14"}), ask,
                     ("OUTPUT", {"verdict": "dismiss", "priority": "low",
                                 "reason": "A shadow on the dock at 02:00:12, judged a look-alike."}))
    run_scripted(triage, model, tools)
    assert triage.stats["CAM-B-1"]["video"] == "look-alike"


def test_budget_hit_goes_to_a_person(tools):
    triage = AgentTriage(request_limit=3, checker_factory=lambda kind, tag: FakeChecker())
    final = run_scripted(triage, scripted(("now", {})), tools)
    assert final["verdict"] == "escalate" and final["priority"] == "medium"
    assert final["reason"].startswith("Agent could not finish")
    assert triage.stats["CAM-B-1"]["overrides"] == ["failure"]
    assert triage.stats["CAM-B-1"]["requests"] == 3
    assert set(final) == KEYS


def test_second_look_limit(tools):
    checker = FakeChecker()
    triage = AgentTriage(checker_factory=lambda kind, tag: checker)
    look = ("second_look", {"camera_id": "CAM-B", "around": "02:00:10", "question": "anyone there?"})
    model = scripted(look, look, look, ("OUTPUT", {"verdict": "escalate", "priority": "high",
                                                   "reason": "A person on the dock at 02:00:12, unexplained."}))
    with triage.agent.override(model=model):
        final = triage(CANDIDATE, tools, [])
    rets = [p for p in returns(triage.last_messages) if p.tool_name == "second_look"]
    assert len(rets) == 3 and "limit" in json.dumps(rets[2].content).lower()
    assert sum(1 for _, _, strong in checker.seen if strong) == 2
    assert triage.stats["CAM-B-1"]["second_looks"] == 2
    assert len(final["evidence"]) >= 1  # the second-look clip


def test_second_look_refused_after_ask_video_used_sonnet(tools):
    checker = FakeChecker(ask_escalated=True)
    triage = AgentTriage(checker_factory=lambda kind, tag: checker)
    model = scripted(("second_look", {"camera_id": "CAM-B", "around": "02:00:10", "question": "q"}),
                     ("OUTPUT", {"verdict": "escalate", "priority": "high", "reason": "A person on the dock, unexplained."}))
    with triage.agent.override(model=model):
        triage(CANDIDATE, tools, [])
    ret = [p for p in returns(triage.last_messages) if p.tool_name == "second_look"][0]
    assert "stronger model" in json.dumps(ret.content)
    assert checker.seen == [] and triage.stats["CAM-B-1"]["second_looks"] == 0


def test_run_file_written(tools, tmp_path):
    run_dir = tmp_path / "run"
    triage = AgentTriage(run_dir=run_dir, checker_factory=lambda kind, tag: FakeChecker())
    model = scripted(("now", {}), ("OUTPUT", {"verdict": "dismiss", "priority": "low",
                                              "reason": "Shadow from a passing light, no person on the dock."}))
    run_scripted(triage, model, tools)
    data = json.loads((run_dir / "CAM-B-1.json").read_text())
    assert {"candidate", "task", "output", "failure", "final", "overrides", "trace", "messages", "stats"} <= set(data)
    assert data["final"]["verdict"] == "dismiss" and data["output"]["verdict"] == "dismiss"
    assert data["trace"][0]["tool"] == "now"
    assert any(m.get("kind") == "response" for m in data["messages"])


# --- evaluate.py with the agent (task 5) ----------------------------------------------------
def test_evaluate_with_scripted_agent(site_dir, tmp_path):
    import evaluate
    triage = AgentTriage(run_dir=tmp_path / "runs", checker_factory=lambda kind, tag: FakeChecker())
    model = scripted(("OUTPUT", {"verdict": "dismiss", "priority": "low",
                                 "reason": "Expected activity: a look-alike, nobody on the footage."}))
    with triage.agent.override(model=model):
        result = evaluate.run(str(site_dir / "site" / "index.json"), 2, triage_fn=triage)
    rows = result["events"]
    assert [r["verdict"] for r in rows] == ["dismiss", "dismiss"]
    for r in rows:
        assert {"cost_usd", "requests", "tool_calls", "tool_errors", "overrides", "video"} <= set(r)
        assert r["requests"] == 1 and r["overrides"] == []
        assert r["video"] is None  # this brain never asked the video model
    s = result["summary"]
    assert s["total_cost_usd"] == pytest.approx(sum(r["cost_usd"] for r in rows))
    assert s["mean_cost_per_alert_usd"] == pytest.approx(s["total_cost_usd"] / 2)
    assert sorted(p.name for p in (tmp_path / "runs").iterdir()) == ["CAM-A-1.json", "CAM-B-1.json"]


class SlowStub:
    """The stub's verdicts, with stats saying each alert took the agent 42 s."""

    def __init__(self):
        self.stats: dict[str, dict] = {}

    def __call__(self, candidate, tools, open_alerts):
        from fakecctv.triage_stub import triage
        self.stats[candidate["candidate_id"]] = {"cost_usd": 0.0, "requests": 1, "tool_calls": 0, "tool_errors": 0,
                                                 "overrides": [], "seconds": 42.0}
        return triage(candidate, tools, open_alerts)


def test_agent_table_has_a_video_column(site_dir, capsys):
    import evaluate

    class VideoStub(SlowStub):
        def __call__(self, candidate, tools, open_alerts):
            out = super().__call__(candidate, tools, open_alerts)
            self.stats[candidate["candidate_id"]]["video"] = "look-alike" if candidate["camera_id"] == "CAM-A" else None
            return out

    result = evaluate.run(str(site_dir / "site" / "index.json"), 2, triage_fn=VideoStub())
    assert [r["video"] for r in result["events"]] == ["look-alike", None]
    evaluate.print_table(result)
    lines = capsys.readouterr().out.splitlines()
    assert "video" in lines[0].split()
    assert "look-alike" in lines[1]
    assert "  -  " in lines[2]


def test_time_to_alert_counts_the_agents_seconds(site_dir):
    """The replay clock stands still while the agent works, so its seconds are added (KPI 3)."""
    import evaluate
    result = evaluate.run(str(site_dir / "site" / "index.json"), 2, triage_fn=SlowStub())
    for r in result["events"]:
        assert r["time_to_alert_s"] == pytest.approx(2 + 42)
        assert r["triage_s"] == 42.0
    assert result["summary"]["median_time_to_alert_s"] == pytest.approx(44)


def test_run_folders_are_named_to_the_second():
    """Two runs started in the same minute must not share a folder."""
    from datetime import datetime

    import evaluate
    d = evaluate.run_dir_for(datetime(2026, 11, 21, 15, 35, 12))
    assert d.name == "20261121-153512"
    assert d.parent == evaluate.ROOT / "runs" / "triage"


# --- evaluate.py --repeats (session 3) ------------------------------------------------------
class ScriptedTriage:
    """An AgentTriage whose brain is a scripted model that always gives one verdict."""

    def __init__(self, verdict: str, priority: str, run_dir: Path):
        self.inner = AgentTriage(run_dir=run_dir, checker_factory=lambda kind, tag: FakeChecker())
        self.model = scripted(("OUTPUT", {"verdict": verdict, "priority": priority,
                                          "reason": f"Scripted {verdict} for the repeats test."}))
        self.stats = self.inner.stats
        self.run_dir = run_dir

    def __call__(self, candidate, tools, open_alerts):
        with self.inner.agent.override(model=self.model):
            return self.inner(candidate, tools, open_alerts)


def test_repeats_aggregate(site_dir, tmp_path):
    """Three runs with a scripted brain: dismiss, then escalate twice. CAM-A-1 is a look-alike, CAM-B-1 real."""
    import evaluate
    plan = {1: ("dismiss", "low"), 2: ("escalate", "high"), 3: ("escalate", "high")}
    made = []

    def make_triage(i):
        t = ScriptedTriage(*plan[i], run_dir=tmp_path / f"stamp-r{i}")
        made.append(t)
        return t

    out = evaluate.run_repeats(str(site_dir / "site" / "index.json"), 3, make_triage, delay_s=2)
    assert len(out["runs"]) == 3 and len({id(t) for t in made}) == 3  # a fresh agent per run
    assert [len(t.stats) for t in made] == [2, 2, 2]  # stats never mix across runs
    for i in (1, 2, 3):
        assert sorted(p.name for p in (tmp_path / f"stamp-r{i}").iterdir()) == ["CAM-A-1.json", "CAM-B-1.json"]

    agg = out["aggregate"]
    assert agg["repeats"] == 3
    by_event = {e["event"]: e for e in agg["events"]}
    assert list(by_event) == ["CAM-A-1", "CAM-B-1"]
    assert by_event["CAM-A-1"]["verdicts"] == ["dismiss", "escalate", "escalate"]
    assert (by_event["CAM-A-1"]["correct"], by_event["CAM-A-1"]["of"]) == (1, 3)
    assert (by_event["CAM-B-1"]["correct"], by_event["CAM-B-1"]["of"]) == (2, 3)
    assert by_event["CAM-B-1"]["real"] is True

    s = agg["summary"]
    assert s["alerts_sent_to_a_person"] == {"mean": pytest.approx(4 / 3, abs=1e-3), "min": 0, "max": 2}
    assert s["real_events_kept_pct"] == {"mean": pytest.approx(200 / 3, abs=1e-3), "min": 0.0, "max": 100.0}
    assert s["detector_events"] == {"mean": 2, "min": 2, "max": 2}
    # run 1 sent nothing to a person, so its median time to alert is None and is left out
    assert s["median_time_to_alert_s"]["min"] == s["median_time_to_alert_s"]["max"]
    totals = [r["summary"]["total_cost_usd"] for r in out["runs"]]
    assert s["total_cost_usd"]["max"] == max(totals) and s["total_cost_usd"]["min"] == min(totals)


def test_aggregate_with_no_numbers_gives_none():
    import evaluate
    run = {"summary": {"median_time_to_alert_s": None},
           "events": [{"event": "E-1", "camera": "C", "type": "t", "first_seen": "02:00:00", "real": True,
                       "verdict": "dismiss", "correct": False}]}
    agg = evaluate.aggregate([run, run])
    assert agg["summary"]["median_time_to_alert_s"] == {"mean": None, "min": None, "max": None}
    assert agg["events"][0]["verdicts"] == ["dismiss", "dismiss"] and agg["events"][0]["correct"] == 0


def test_print_aggregate(site_dir, capsys):
    import evaluate
    out = evaluate.run_repeats(str(site_dir / "site" / "index.json"), 2, lambda i: None, delay_s=2)  # the stub
    evaluate.print_aggregate(out["aggregate"])
    text = capsys.readouterr().out
    assert "correct" in text and "2/2" in text
    assert "mean" in text and "min" in text and "max" in text
    assert "alerts sent to a person" in text


def test_repeat_run_folders_share_one_stamp():
    from datetime import datetime

    import evaluate
    now = datetime(2026, 11, 21, 15, 35, 12)
    assert evaluate.run_dir_for(now, 2).name == "20261121-153512-r2"
    assert evaluate.run_dir_for(now).name == "20261121-153512"  # one run keeps the old name


def test_main_repeats_writes_every_run_and_the_aggregate(site_dir, tmp_path, monkeypatch, capsys):
    """The stub path: free, never loads .env."""
    import evaluate
    out = tmp_path / "rep.json"
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--index", str(site_dir / "site" / "index.json"),
                                      "--delay", "2", "--repeats", "2", "--json", str(out)])
    evaluate.main()
    data = json.loads(out.read_text())
    assert set(data) == {"runs", "aggregate"} and len(data["runs"]) == 2
    assert data["aggregate"]["repeats"] == 2
    assert "run 2/2" in capsys.readouterr().out

    one = tmp_path / "one.json"
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--index", str(site_dir / "site" / "index.json"),
                                      "--delay", "2", "--json", str(one)])
    evaluate.main()
    assert set(json.loads(one.read_text())) == {"summary", "events"}  # --repeats 1: unchanged shape
