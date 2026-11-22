"""The review step: decisions, actions, the audit summary and the terminal screen. No API calls.

    python -m pytest tests/test_review.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic_ai import models

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import review  # noqa: E402
from agentlab import audit  # noqa: E402
from agentlab import review as logic  # noqa: E402
from d3d5_helpers import kept_run, no_env  # noqa: E402,F401
from fakecctv.alerts import AlertStore  # noqa: E402

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def run(site_dir, tmp_path) -> Path:
    """A-001 (CAM-A-1) dismissed by the agent, A-002 (CAM-B-1) escalated."""
    return kept_run(site_dir, tmp_path / "run")


def add(run_dir: Path, cid: str, verdict: str, priority: str, at: str, linked_to: str | None = None,
        reason: str = "A person is on the footage.", evidence: list[str] | None = None) -> dict:
    cand = {"candidate_id": cid, "camera_id": cid.rsplit("-", 1)[0], "zone": "Waiting area",
            "kind": "unattended_object", "first_seen": f"2018-03-11T{at}"}
    return AlertStore(run_dir).add(cand, {"verdict": verdict, "priority": priority, "reason": reason,
                                          "evidence": evidence or [], "linked_to": linked_to},
                                   [], datetime.fromisoformat(f"2018-03-11T{at}"))


def typed(monkeypatch, *answers):
    """The keys a guard types; running out of them is end of input."""
    left = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(left)
        except StopIteration:
            raise EOFError from None
    monkeypatch.setattr("builtins.input", fake_input)


def of_type(run_dir: Path, kind: str) -> list[dict]:
    return [e for e in audit.read(run_dir) if e["type"] == kind]


# --- the lists ------------------------------------------------------------------------------
def test_pending_and_closed_lists(run):
    assert [a["id"] for a in logic.pending(run)] == ["A-002"]
    assert [a["id"] for a in logic.closed(run)] == ["A-001"]
    logic.decide(run, "A-002", "approve")
    logic.decide(run, "A-001", "confirm")
    assert logic.pending(run) == [] and logic.closed(run) == []


def test_pending_is_by_priority_then_time_and_closed_includes_linked(tmp_path):
    add(tmp_path, "C-01-1", "escalate", "low", "13:50:00")
    add(tmp_path, "C-02-1", "escalate", "high", "13:55:00")
    add(tmp_path, "C-03-1", "escalate", "medium", "13:51:00")
    add(tmp_path, "C-04-1", "escalate", "high", "13:52:00")
    add(tmp_path, "C-05-1", "linked", "high", "13:53:00", linked_to="A-004")
    assert [a["id"] for a in logic.pending(tmp_path)] == ["A-004", "A-002", "A-003", "A-001"]
    assert [a["id"] for a in logic.closed(tmp_path)] == ["A-005"]


def test_find_alert_by_candidate_id(run):
    alerts = AlertStore(run).all()
    assert logic.find_alert(alerts, "CAM-B-1")["id"] == "A-002"
    assert logic.find_alert(alerts, "A-002")["candidate"]["candidate_id"] == "CAM-B-1"
    with pytest.raises(ValueError) as err:
        logic.find_alert(alerts, "A-009")
    assert str(err.value) == "No alert A-009 in this run."


# --- decisions ------------------------------------------------------------------------------
def test_approve_writes_decision_and_action(run):
    entry = logic.decide(run, "CAM-B-1", "approve")
    assert [entry] == of_type(run, "decision")
    assert (entry["alert_id"], entry["candidate_id"]) == ("A-002", "CAM-B-1")
    assert (entry["decision"], entry["agreed"], entry["agent_verdict"]) == ("approve", True, "escalate")
    assert entry["reviewer"] == "Guard on duty" and entry["ts"]
    assert entry["alert_site_time"] == AlertStore(run).all()[1]["created"]
    [action] = of_type(run, "action")
    assert action["alert_id"] == "A-002" and action["approved_by"] == "Guard on duty"
    assert action["action"] == ("The guard on duty checks Dock and decides on dispatch. "
                                "The system never contacts the police.")
    assert action["simulated"] is True
    assert [e["type"] for e in audit.read(run)][-2:] == ["decision", "action"]  # never an action first
    assert json.loads((run / "decisions.jsonl").read_text())["alert_id"] == "A-002"


def test_approved_alert_is_still_open_for_the_kit(run):
    """The kit knows "approved"; with "approve" the alert would leave open_alerts()."""
    logic.decide(run, "A-002", "approve")
    assert [a["id"] for a in AlertStore(run).open_alerts()] == ["A-002"]


@pytest.mark.parametrize("ref, decision, word", [
    ("A-002", "approve", "approved"), ("A-002", "dismiss", "dismissed by guard"),
    ("A-001", "confirm", "confirmed"), ("A-001", "reopen", "reopened"),
])
def test_decisions_file_uses_the_kits_words(run, ref, decision, word):
    logic.decide(run, ref, decision, reason="Checked the clip")
    row = json.loads((run / "decisions.jsonl").read_text())
    assert (row["decision"], row["note"]) == (word, "Checked the clip")


@pytest.mark.parametrize("ref, decision", [("A-002", "dismiss"), ("A-001", "reopen")])
@pytest.mark.parametrize("reason", ["", "   "])
def test_dismiss_needs_reason(run, ref, decision, reason):
    before = (run / audit.AUDIT_FILE).read_bytes()
    with pytest.raises(ValueError) as err:
        logic.decide(run, ref, decision, reason=reason)
    assert str(err.value) == "A reason is required to dismiss or reopen."
    assert (run / audit.AUDIT_FILE).read_bytes() == before and not (run / "decisions.jsonl").exists()


def test_second_decision_refused(run):
    logic.decide(run, "A-002", "approve")
    before = (run / audit.AUDIT_FILE).read_bytes()
    with pytest.raises(ValueError) as err:
        logic.decide(run, "CAM-B-1", "dismiss", reason="Changed my mind")
    assert str(err.value) == "A-002 was already decided (approve)."
    assert (run / audit.AUDIT_FILE).read_bytes() == before


@pytest.mark.parametrize("ref, decision, verdict", [
    ("A-001", "approve", "dismiss"), ("A-001", "dismiss", "dismiss"),
    ("A-002", "confirm", "escalate"), ("A-002", "reopen", "escalate"), ("A-002", "maybe", "escalate"),
])
def test_wrong_decision_for_verdict_refused(run, ref, decision, verdict):
    with pytest.raises(ValueError, match=f"verdict was {verdict}"):
        logic.decide(run, ref, decision, reason="x")
    assert of_type(run, "decision") == [] and of_type(run, "action") == []


@pytest.mark.parametrize("ref, decision", [("A-002", "dismiss"), ("A-001", "confirm"), ("A-001", "reopen")])
def test_only_an_approval_logs_an_action(run, ref, decision):
    entry = logic.decide(run, ref, decision, reason="Checked")
    assert of_type(run, "action") == []
    assert entry["agreed"] is (decision == "confirm")


def test_decisions_only_append_to_the_audit(run):
    before = (run / audit.AUDIT_FILE).read_bytes()
    logic.decide(run, "A-002", "approve")
    logic.decide(run, "A-001", "confirm")
    assert (run / audit.AUDIT_FILE).read_bytes().startswith(before)


# --- the summary ----------------------------------------------------------------------------
def test_summary_before_any_decision(run):
    assert logic.summary(run) == {
        "alerts": 2, "escalated": 1, "closed_by_agent": 1, "decisions": 0, "approved": 0, "dismissed": 0,
        "confirmed": 0, "reopened": 0, "overrides": 0, "override_rate": None, "actions": 0, "reports": 0}


def test_reopen_counts_as_override(run):
    logic.decide(run, "A-002", "approve")
    logic.decide(run, "A-001", "reopen", reason="Person not on roster")
    s = logic.summary(run)
    assert (s["overrides"], s["override_rate"]) == (1, 0.5)
    assert (s["decisions"], s["approved"], s["reopened"], s["actions"]) == (2, 1, 1, 1)


def test_dismissing_an_escalation_is_an_override(run):
    logic.decide(run, "A-002", "dismiss", reason="A shadow")
    assert (logic.summary(run)["overrides"], logic.summary(run)["override_rate"]) == (1, 1.0)


def test_summary_counts_each_reported_alert_once(run):
    for _ in range(2):
        audit.append(run, {"type": "report", "alert_id": "A-002"})
    assert logic.summary(run)["reports"] == 1


# --- how an alert is shown ------------------------------------------------------------------
def test_render_alert_layout(tmp_path):
    clip = "evidence/CAM-05-1/CAM-05_20180311-135837_135927.mp4"
    alert = add(tmp_path, "CAM-05-1", "escalate", "medium", "13:58:57", reason="A bag was left.", evidence=[clip])
    assert logic.render_alert(alert, color=False).splitlines() == [
        "A-001  MEDIUM  unattended_object  CAM-05 Waiting area  first seen 13:58:57",
        "Agent: escalate. A bag was left.",
        f"Evidence: {clip}",
        "Proposed action: A guard checks the object in Waiting area in person. It is not moved before it is checked.",
    ]


def test_render_closed_alert_shows_the_link_and_no_action(tmp_path):
    alert = add(tmp_path, "CAM-02-1", "linked", "high", "13:51:29", linked_to="A-007")
    text = logic.render_alert(alert, color=False)
    assert "Agent: linked to A-007." in text and "Proposed action" not in text
    assert "evidence clip missing" in text


def test_render_alert_without_colour_has_no_escape_codes(run):
    assert "\033" not in logic.render_alert(logic.pending(run)[0], color=False)


@pytest.mark.parametrize("priority, code", [("high", "31"), ("medium", "33"), ("low", "2")])
def test_render_alert_colours_only_the_priority(tmp_path, priority, code):
    alert = add(tmp_path, "CAM-05-1", "escalate", priority, "13:58:57")
    text = logic.render_alert(alert, color=True)
    assert f"\033[{code}m{priority.upper()}\033[0m" in text and text.count("\033") == 2


def test_render_drops_control_characters_from_model_text(tmp_path):
    alert = add(tmp_path, "CAM-05-1", "escalate", "high", "13:58:57",
                reason="A bag\033[2J was\nleft\x07 here.")
    text = logic.render_alert(alert, color=False)
    assert "\033" not in text and "\x07" not in text and len(text.splitlines()) == 4


# --- the command ----------------------------------------------------------------------------
def test_cli_scripted_decisions(run, capsys):
    code = review.main(["--run", str(run), "--decide", "CAM-B-1=approve",
                        "--decide", "CAM-A-1=reopen:Person not on roster"])
    out = capsys.readouterr().out
    assert code == 0
    assert "(real time) for the alert first seen 02:00:12 (site time)" in out
    assert [d["decision"] for d in of_type(run, "decision")] == ["approve", "reopen"]
    assert of_type(run, "decision")[1]["reason"] == "Person not on roster"
    assert review.main(["--run", str(run), "--summary"]) == 0
    assert "override rate" in capsys.readouterr().out


def test_cli_reason_may_hold_colons_and_equals_and_reviewer_is_recorded(run):
    review.main(["--run", str(run), "--reviewer", "Control room", "--decide", "A-002=dismiss:Seen 02:00:12, x=y"])
    [entry] = of_type(run, "decision")
    assert (entry["reason"], entry["reviewer"]) == ("Seen 02:00:12, x=y", "Control room")


def test_cli_rerun_refuses_and_carries_on(run, capsys):
    review.main(["--run", str(run), "--decide", "A-002=approve"])
    code = review.main(["--run", str(run), "--decide", "A-002=approve", "--decide", "A-001=confirm"])
    assert code == 1
    assert "A-002 was already decided (approve)." in capsys.readouterr().out
    assert [d["alert_id"] for d in of_type(run, "decision")] == ["A-002", "A-001"]


@pytest.mark.parametrize("bad", ["A-001", "A-001=perhaps", "A-001=reopen", "A-001=reopen: ", "=confirm"])
def test_cli_malformed_decide_applies_nothing(run, bad):
    with pytest.raises(SystemExit) as err:
        review.main(["--run", str(run), "--decide", "A-002=approve", "--decide", bad])
    assert err.value.code == 2
    assert of_type(run, "decision") == []


def test_screen_dismiss_asks_for_a_reason_until_it_gets_one(run, monkeypatch, capsys):
    typed(monkeypatch, "d", "", "d", "Kneeling, not a fall")
    assert review.main(["--run", str(run)]) == 0
    assert "A reason is required" in capsys.readouterr().out
    [entry] = of_type(run, "decision")
    assert (entry["decision"], entry["reason"]) == ("dismiss", "Kneeling, not a fall")


def test_screen_approve_prints_the_decision_time(run, monkeypatch, capsys):
    typed(monkeypatch, "a")
    review.main(["--run", str(run)])
    out = capsys.readouterr().out
    assert "decided " in out and "(real time) for the alert first seen 02:00:12 (site time)" in out
    assert "\033" not in out  # not a terminal
    assert len(of_type(run, "action")) == 1


@pytest.mark.parametrize("keys", [("q",), ("s",), (), ("?", "c", "q")])
def test_screen_quit_skip_end_of_input_and_other_keys_decide_nothing(run, monkeypatch, keys):
    typed(monkeypatch, *keys)
    assert review.main(["--run", str(run)]) == 0
    assert of_type(run, "decision") == []


def test_screen_ctrl_c_quits_cleanly(run, monkeypatch):
    def interrupt(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupt)
    assert review.main(["--run", str(run)]) == 0
    assert of_type(run, "decision") == []


@pytest.mark.parametrize("keys, decision", [(("c",), "confirm"), (("r", "Not on roster"), "reopen")])
def test_screen_closed_mode(run, monkeypatch, keys, decision):
    typed(monkeypatch, *keys)
    review.main(["--run", str(run), "--closed"])
    assert [(d["alert_id"], d["decision"]) for d in of_type(run, "decision")] == [("A-001", decision)]


def test_screen_opens_the_first_clip_not_a_still(tmp_path, monkeypatch):
    add(tmp_path, "CAM-05-1", "escalate", "high", "13:58:57",
        evidence=["evidence/CAM-05-1/frame.jpg", "evidence/CAM-05-1/clip.mp4"])
    clip = tmp_path / "evidence" / "CAM-05-1" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"video")
    opened = []
    monkeypatch.setattr(review.subprocess, "Popen", lambda cmd, **kw: opened.append(cmd))
    typed(monkeypatch, "o", "q")
    review.main(["--run", str(tmp_path)])
    assert len(opened) == 1 and opened[0][1] == str(clip.resolve())


def test_screen_open_with_a_missing_clip_says_so(run, monkeypatch, capsys):
    for clip in run.glob("evidence/CAM-B-1/*.mp4"):
        clip.unlink()
    monkeypatch.setattr(review.subprocess, "Popen", lambda *a, **kw: pytest.fail("nothing to open"))
    typed(monkeypatch, "o", "q")
    review.main(["--run", str(run)])
    assert "evidence clip missing" in capsys.readouterr().out


def test_old_run_folder_message(tmp_path):
    with pytest.raises(SystemExit) as err:
        review.main(["--run", str(tmp_path)])
    assert str(err.value) == ("This run folder has no alerts.jsonl; it was made before the review step. "
                              "Run evaluate.py --triage agent again.")
