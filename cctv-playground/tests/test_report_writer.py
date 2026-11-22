"""Incident reports: facts from the run, the checker, the draft and the rendering. No API calls.

    python -m pytest tests/test_report_writer.py -q
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

from agentlab import audit, report_writer  # noqa: E402
from agentlab import review as logic  # noqa: E402
from d3d5_helpers import no_env  # noqa: E402,F401
from fakecctv.alerts import AlertStore  # noqa: E402

models.ALLOW_MODEL_REQUESTS = False

DAY = "2018-03-11T"
OWN = "CAM-05_20180311-135837_135927.mp4"
NEIGHBOUR = "CAM-06_20180311-135840_135920.mp4"


# --- hand-written runs ----------------------------------------------------------------------
def clip_step(name: str, requested: str = "13:58:37", end: str = "13:59:27") -> dict:
    camera = name.split("_")[0]
    return {"tool": "get_clip", "ok": True, "args": {"camera_id": camera, "start": requested, "end": end},
            "result": {"camera_id": camera, "start": requested, "end": end, "path": f"/tmp/work/{name}"}}


def ask_step(name: str, *events: dict, ok: bool = True) -> dict:
    return {"tool": "ask_video", "ok": ok, "args": {"clip_path": f"/tmp/work/{name}", "question": "q"},
            "result": {"events": list(events), "model": "claude-sonnet-5-5"} if ok else "unavailable"}


def event(start_s: float, end_s: float = 50.0, kind: str = "unattended_object", real: bool = True,
          what: str = "A bag is left by the bench.") -> dict:
    return {"event_type": kind, "start_s": start_s, "end_s": end_s, "real": real, "reason": what}


def log_step(rows: list[dict], count: int | None = None, door: str | None = None) -> dict:
    return {"tool": "access_log", "ok": True, "args": {"start": "13:48:57", "end": "13:59:27", "door": door},
            "result": {"rows": rows, "count": len(rows) if count is None else count}}


def roster_step(rows: list[dict]) -> dict:
    return {"tool": "roster", "ok": True, "args": {"at": "13:58:57"}, "result": {"rows": rows, "count": len(rows)}}


def written_run(run: Path, trace: list[dict], *, cid: str = "CAM-05-1", first_seen: str = "13:58:57",
                detected: str = "13:59:27", reason: str = "A bag was left by the bench.", verdict: str = "escalate",
                linked_to: str | None = None, kept: tuple[str, ...] = (OWN,)) -> dict:
    """One alert as evaluate.run keeps it: alerts.jsonl, its run file, evidence and the verdict entry."""
    cand = {"candidate_id": cid, "camera_id": cid.rsplit("-", 1)[0], "zone": "Waiting area",
            "kind": "unattended_object", "first_seen": DAY + first_seen, "detected_at": DAY + detected}
    evidence = []
    for name in kept:
        path = run / "evidence" / cid / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        evidence.append(f"evidence/{cid}/{name}")
    final = {"verdict": verdict, "priority": "medium", "reason": reason, "evidence": evidence, "linked_to": linked_to}
    alert = AlertStore(run).add(cand, final, trace, datetime.fromisoformat(DAY + detected))
    (run / f"{cid}.json").write_text(json.dumps({"candidate": cand, "final": final, "trace": trace}))
    audit.append(run, audit.verdict_entry(alert, "Demo site", None))
    return alert


# --- the facts ------------------------------------------------------------------------------
def test_collect_facts_header_fields(tmp_path):
    written_run(tmp_path, [clip_step(OWN)])
    f = report_writer.collect_facts(tmp_path, "CAM-05-1")
    assert (f["site"], f["alert_id"], f["candidate_id"]) == ("Demo site", "A-001", "CAM-05-1")
    assert (f["camera"], f["zone"], f["kind"]) == ("CAM-05", "Waiting area", "unattended_object")
    assert (f["first_seen"], f["detected_at"], f["created"]) == ("13:58:57", "13:59:27", "13:59:27")
    assert (f["verdict"], f["priority"], f["linked_to"]) == ("escalate", "medium", None)
    assert f["evidence"] == [f"evidence/CAM-05-1/{OWN}"] and f["evidence_missing"] == []


def test_collect_facts_converts_video_times_to_site_time(tmp_path):
    written_run(tmp_path, [clip_step(OWN), ask_step(OWN, event(22.0, 50.0))])
    [e] = report_writer.collect_facts(tmp_path, "A-001")["video_events"]
    assert (e["time"], e["end"]) == ("13:58:59", "13:59:27")
    assert (e["type"], e["real"], e["what"]) == ("unattended_object", True, "A bag is left by the bench.")
    assert (e["camera"], e["model"]) == ("CAM-05", "claude-sonnet-5-5")


def test_collect_facts_uses_the_real_start_of_a_clamped_clip(tmp_path):
    """CAM-03-1 in the 21 Nov runs: asked for 13:49:40, the recording starts at 13:50:00."""
    name = "CAM-03_20180311-135000_135010.mp4"
    written_run(tmp_path, [clip_step(name, requested="13:49:40", end="13:50:10"), ask_step(name, event(2.0, 10.0))],
                cid="CAM-03-1", first_seen="13:50:00", detected="13:50:10", kept=(name,))
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert (f["video_events"][0]["time"], f["video_events"][0]["end"]) == ("13:50:02", "13:50:10")
    assert "13:49:40" not in f["fact_times"]


def test_collect_facts_maps_a_second_look_to_its_own_clip(tmp_path):
    look = "CAM-05_20180311-135844_135914.mp4"
    step = {"tool": "second_look", "ok": True, "args": {"camera_id": "CAM-05", "around": "13:58:59"},
            "result": {"camera_id": "CAM-05", "start": "13:58:44", "end": "13:59:14", "model": "claude-sonnet-5-5",
                       "clip_path": f"/tmp/work/{look}", "events": [event(15.0, 30.0)]}}
    written_run(tmp_path, [step], kept=(look,))
    [e] = report_writer.collect_facts(tmp_path, "A-001")["video_events"]
    assert (e["time"], e["end"]) == ("13:58:59", "13:59:14")


def test_collect_facts_ignores_failed_tool_calls(tmp_path):
    written_run(tmp_path, [clip_step(OWN), ask_step(OWN, ok=False),
                           {"tool": "access_log", "ok": False, "args": {"start": "14:10", "end": "14:20"},
                            "result": "The access log only runs to 13:59:27"}])
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert f["video_events"] == [] and f["context"] == []
    assert "14:20:00" not in f["fact_times"]


def test_collect_facts_reads_context_and_decision(tmp_path):
    badge = {"time": "13:54:22", "door": "Main gate", "badge": "B-0412", "holder": "Weekend guard",
             "result": "granted"}
    shift = {"start": "13:00", "end": "15:00", "who": "Visitors (public opening)", "role": "Visitors",
             "zones": "Lobby; Waiting area", "note": "Open to the public"}
    written_run(tmp_path, [clip_step(OWN), log_step([badge]), roster_step([shift])])
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert f["decision"] is None and f["action"] is None
    log, roster = f["context"]
    assert log["source"] == "access_log" and log["time"] == "13:54:22"
    assert all(v in log["text"] for v in badge.values())
    assert roster["source"] == "roster" and "Visitors (public opening)" in roster["text"]
    assert {"13:54:22", "13:00:00", "15:00:00"} <= set(f["fact_times"])

    logic.decide(tmp_path, "A-001", "approve")
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert f["decision"]["decision"] == "approve" and f["decision"]["reviewer"] == "Guard on duty"
    assert f["action"].startswith("A guard checks the object in Waiting area")


def test_an_empty_lookup_is_a_fact(tmp_path):
    written_run(tmp_path, [log_step([], door="Main gate"), roster_step([])])
    f = report_writer.collect_facts(tmp_path, "A-001")
    log, roster = (c["text"] for c in f["context"])
    assert "No badge-log entries" in log and "13:48:57" in log and "13:59:27" in log and "Main gate" in log
    assert "Nobody on the roster at 13:58:57" in roster
    assert "13:48:57" in f["fact_times"]


def test_a_cut_context_list_says_so(tmp_path):
    rows = [{"time": f"13:5{i}:00", "door": "Main gate", "badge": f"B-{i}", "holder": "Staff", "result": "granted"}
            for i in range(5)]
    written_run(tmp_path, [log_step(rows, count=8)])
    assert "5 of 8" in report_writer.collect_facts(tmp_path, "A-001")["context"][-1]["text"]


def test_a_time_only_in_the_reason_is_not_a_fact(tmp_path):
    """The kneel in two runs of 21 Nov: detected 13:57:31, and the reason says 13:57:43."""
    name = "CAM-04_20180311-135701_135731.mp4"
    written_run(tmp_path, [clip_step(name), ask_step(name, event(21.6, 30.0, what="Kneels at 13:57:50."))],
                cid="CAM-04-2", first_seen="13:57:21", detected="13:57:31", kept=(name,),
                reason="A person goes down onto their knees at about 13:57:43.")
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert "13:57:43" not in f["fact_times"] and "13:57:50" not in f["fact_times"]
    assert f["fact_times"] == sorted(f["fact_times"])
    assert len(report_writer.check_report(["The person kneels at 13:57:43."], f)) == 1


def test_an_inverted_badge_window_is_not_a_fact(tmp_path):
    """CAM-07-1 in 20261121-165846-r3: the agent asked 14:52:25 to 14:02:35 and got an empty list."""
    step = log_step([])
    step["args"] = {"start": "14:52:25", "end": "14:02:35", "door": "Stairwell door"}
    written_run(tmp_path, [step], cid="CAM-07-1", first_seen="14:02:25", detected="14:02:35", kept=())
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert f["context"] == [] and "14:52:25" not in f["fact_times"]


def test_a_badge_window_over_midnight_is_a_fact(tmp_path):
    step = log_step([])
    step["args"] = {"start": "23:55:00", "end": "00:05:00"}
    written_run(tmp_path, [step], first_seen="00:04:50", detected="00:05:00", kept=())
    assert "23:55:00" in report_writer.collect_facts(tmp_path, "A-001")["fact_times"]


def test_a_roster_question_about_a_later_time_adds_no_fact_time(tmp_path):
    step = roster_step([])
    step["args"] = {"at": "14:30:00"}
    written_run(tmp_path, [step], kept=())
    assert "14:30:00" not in report_writer.collect_facts(tmp_path, "A-001")["fact_times"]


def test_cameras_in_the_facts_include_neighbour_evidence_and_the_link_target(tmp_path):
    written_run(tmp_path, [], cid="CAM-07-1", first_seen="13:58:00", detected="13:58:10", kept=())
    written_run(tmp_path, [clip_step(OWN), clip_step(NEIGHBOUR), ask_step(NEIGHBOUR, event(5.0))],
                verdict="linked", linked_to="A-001", kept=(OWN, NEIGHBOUR))
    f = report_writer.collect_facts(tmp_path, "A-002")
    assert set(f["cameras"]) == {"CAM-05", "CAM-06", "CAM-07"}
    assert f["linked_alert"] == {"id": "A-001", "camera": "CAM-07", "first_seen": "13:58:00"}
    assert "13:58:00" in f["fact_times"]


def test_evidence_that_was_never_copied_or_is_gone_is_missing(tmp_path):
    written_run(tmp_path, [clip_step(OWN), clip_step(NEIGHBOUR)], kept=(OWN,))
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert f["evidence_missing"] == [f"evidence/CAM-05-1/{NEIGHBOUR}"]
    (tmp_path / "evidence" / "CAM-05-1" / OWN).unlink()
    f = report_writer.collect_facts(tmp_path, "A-001")
    assert f["evidence"] == [] and len(f["evidence_missing"]) == 2


# --- the checker ----------------------------------------------------------------------------
FACTS = {"cameras": ["CAM-05", "CAM-06"], "fact_times": ["13:00:00", "13:58:57", "13:59:27"]}


def check(*texts, timeline_times=()):
    return report_writer.check_report(list(texts), FACTS, timeline_times=timeline_times)


def test_check_flags_invented_time():
    [flag] = check("The bag was left at 13:41:00.")
    assert "13:41:00" in flag


@pytest.mark.parametrize("time", ["13:58:55", "13:58:57", "13:58:59"])
def test_check_accepts_time_within_two_seconds(time):
    assert check(f"The bag was left at {time}.") == []


@pytest.mark.parametrize("time", ["13:58:54", "13:59:00"])
def test_check_flags_time_three_seconds_away(time):
    assert len(check(f"At {time}.")) == 1


def test_check_tolerance_crosses_a_minute_and_midnight():
    facts = {"cameras": [], "fact_times": ["13:59:59", "23:59:59"]}
    assert report_writer.check_report(["At 14:00:01 and at 00:00:01."], facts) == []


def test_check_flags_am_pm_and_minute_mismatch():
    flags = check("Seen at 1:58 pm, then again at 13:42.")
    assert len(flags) == 2
    assert any("time not in site format (HH:MM:SS)" in f and "1:58 pm" in f for f in flags)
    assert any("13:42" in f for f in flags)


@pytest.mark.parametrize("time", ["2 pm", "1:58PM", "1.58 p.m.", "01:58:57 pm"])
def test_check_flags_each_am_pm_form_once(time):
    [flag] = check(f"Seen at {time} today.")
    assert "time not in site format (HH:MM:SS)" in flag


def test_check_accepts_a_fact_minute_and_does_not_split_seconds():
    assert check("Open from 13:00, seen 13:58 and checked 13:59:27.") == []


@pytest.mark.parametrize("time", ["25:10", "13:58:99"])
def test_check_flags_an_impossible_time(time):
    assert len(check(f"At {time}.")) == 1


def test_check_flags_unknown_camera_and_gender_words():
    flags = check("a woman on CAM-09")
    assert len(flags) == 2
    assert any("CAM-09" in f for f in flags) and any("woman" in f for f in flags)


def test_check_accepts_the_neighbour_and_candidate_ids():
    assert check("CAM-05-1 is on CAM-05, and CAM-06 shows the same person.") == []


def test_check_knows_camera_ids_with_letters():
    facts = {"cameras": ["CAM-A"], "fact_times": []}
    assert report_writer.check_report(["Seen on CAM-A (CAM-A-1)."], facts) == []
    assert "CAM-B" in report_writer.check_report(["Seen on CAM-B."], facts)[0]


@pytest.mark.parametrize("word", (
    "man men woman women male males female females boy boys girl girls lady ladies gentleman gentlemen guy guys "
    "he she him her his hers elderly young teenager teenagers child children kid kids").split())
def test_check_flags_each_gender_or_age_word(word):
    [flag] = check(f"Then {word.upper()} appeared.")
    assert word.upper() in flag


def test_check_does_not_flag_words_that_only_contain_one():
    assert check("The manager saw a person in the hallway by the shed; the theme was mentioned.") == []


def test_check_flags_filler_phrases():
    [flag] = check("It is worth noting that a person entered.")
    assert flag.startswith("filler phrase:")


@pytest.mark.parametrize("time", ["unknown", "shortly after", "", "13:58:57 or later"])
def test_check_flags_a_timeline_time_that_is_not_a_site_time(time):
    [flag] = check(timeline_times=[time])
    assert "time not in site format (HH:MM:SS)" in flag


def test_check_timeline_times_are_also_matched_against_the_facts():
    assert check(timeline_times=["13:58:57", "13:59"]) == []
    [flag] = check(timeline_times=["13:41:00"])
    assert "13:41:00" in flag


def test_check_clean_text_has_no_flags():
    assert check("A person left a dark bag in the Waiting area on CAM-05 at 13:58:57.",
                 "An alert was raised at 13:59:27.") == []
