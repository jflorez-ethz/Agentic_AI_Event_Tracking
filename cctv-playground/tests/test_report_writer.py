"""Incident reports: facts from the run, the checker, the draft and the rendering. No API calls.

    python -m pytest tests/test_report_writer.py -q
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2
import pytest
from pydantic_ai import ModelResponse, ToolCallPart, models
from pydantic_ai.models.function import FunctionModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import report  # noqa: E402
from agentlab import audit, report_writer, usage  # noqa: E402
from agentlab import review as logic  # noqa: E402
from d3d5_helpers import kept_run, no_env  # noqa: E402,F401
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


# --- task 5: the draft, the still, the rendering and report.py ------------------------------
DRAFT = {
    "title": "Person on the dock",
    "summary": "A person walked onto the dock at 02:00:12. The guard on duty was asked to decide.",
    "timeline": [{"time": "02:00:12", "what": "A person walks onto the dock."}],
    "context_checked": ["The badge log and the roster were read."],
    "open_points": ["Who the person is."],
}


def writer_for(draft: dict | None = None, seen: list | None = None):
    """A report writer whose model returns a fixed draft."""
    def fn(messages, info):
        if seen is not None:
            seen.append((messages, info))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, draft or DRAFT)])
    return report_writer.build_writer(FunctionModel(fn))


@pytest.fixture
def run(site_dir, tmp_path) -> Path:
    """A kept run on the test site; the video check saw a real person 10 s into each clip."""
    return kept_run(site_dir, tmp_path / "run", events=[event(10.0, 14.0, kind="after_hours_person")])


@pytest.fixture
def approved(run) -> Path:
    logic.decide(run, "A-002", "approve")
    return run


def section(text: str, name: str) -> str:
    return text.split(f"## {name}\n", 1)[1].split("\n## ", 1)[0]


def test_writer_has_no_tools_and_no_sampling_settings(approved, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    writer = report_writer.build_writer()  # builds without a key
    assert not {"temperature", "top_p", "top_k"} & set(writer.model_settings or {})
    seen = []

    def fn(messages, info):
        seen.append(info)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, DRAFT)])

    with writer.override(model=FunctionModel(fn)):
        report_writer.write_report(approved, "A-002", writer=writer)
    assert seen[0].function_tools == [] and not seen[0].allow_text_output


def test_writer_instructions():
    text = " ".join(report_writer.INSTRUCTIONS.split())
    for part in ("only the facts", "fact_times", "HH:MM:SS", "a person", "gender, age or ethnicity",
                 "2 to 4 short sentences", "not carried out", "Open points"):
        assert part in text
    for phrase in report_writer.FILLER_PHRASES:
        assert phrase in text


def test_draft_has_no_action_field():
    assert set(report_writer.ReportDraft.model_fields) == {"title", "summary", "timeline", "context_checked",
                                                           "open_points"}


@pytest.mark.parametrize("raw, neutral", [
    ("A woman in a blue jacket", "A person in a blue jacket"),
    ("Two men and a boy", "Two people and a person"),
    ("an elderly woman with a bag", "a person with a bag"),
    ("a young man", "a person"),
    ("a male person", "a person"),
    ("Woman sets a bag down", "Person sets a bag down"),
    ("The manager by the shed", "The manager by the shed"),
])
def test_neutral_replaces_gender_and_age_nouns(raw, neutral):
    assert report_writer.neutral(raw) == neutral


def test_writer_input_is_scrubbed(tmp_path):
    """The bag alert in two runs of 21 Nov said "a woman", in the reason and in the video answer."""
    written_run(tmp_path, [clip_step(OWN), ask_step(OWN, event(22.0, what="A woman in blue leaves a bag."))],
                reason="A woman in a blue jacket left a bag.")
    logic.decide(tmp_path, "A-001", "approve", reason="The woman is gone")
    seen = []
    draft = {**DRAFT, "summary": "A bag was left.", "timeline": []}
    report_writer.write_report(tmp_path, "A-001", writer=writer_for(draft, seen))
    [prompt] = [p.content for m in seen[0][0] for p in m.parts if p.part_kind == "user-prompt"]
    assert not re.search(r"\bwoman\b", prompt, re.I)
    assert "A person in a blue jacket left a bag." in prompt and "A person in blue leaves a bag." in prompt
    given = json.loads(prompt[prompt.index("{"):])
    assert given["fact_times"] == report_writer.collect_facts(tmp_path, "A-001")["fact_times"]
    assert "ts" not in given["decision"]  # the real clock is not a site time


def test_report_refused_for_unapproved_alert(run):
    before = (run / audit.AUDIT_FILE).read_bytes()
    seen = []
    with pytest.raises(ValueError) as err:
        report_writer.write_report(run, "CAM-B-1", writer=writer_for(seen=seen))
    assert str(err.value) == "A-002 is not approved; approve it in review.py first, or use --force."
    assert seen == [] and not (run / "reports").exists()
    assert (run / audit.AUDIT_FILE).read_bytes() == before


def test_report_refused_for_a_dismissed_alert(run):
    logic.decide(run, "A-002", "dismiss", reason="A shadow")
    with pytest.raises(ValueError, match="is not approved"):
        report_writer.write_report(run, "A-002", writer=writer_for())


def test_report_written_with_header_from_facts(approved):
    draft = {**DRAFT, "title": "Something on CAM-A in the Yard"}
    path = report_writer.write_report(approved, "A-002", writer=writer_for(draft))
    assert path == approved / "reports" / "A-002.md"
    text = path.read_text()
    table = "\n".join(line for line in text.splitlines() if line.startswith("|"))
    for value in ("A-002", "Test site", "CAM-B Dock", "after_hours_person", "02:00:12", "high", "escalate",
                  "approve by Guard on duty", "(real time)", "(site time)"):
        assert value in table
    assert "CAM-A" not in table  # nothing in the table comes from the model
    assert "Reviewed by: ____  Date: ____" in text and "Draft: needs sign-off by the reviewer." in text

    [entry] = [e for e in audit.read(approved) if e["type"] == "report"]
    assert (entry["alert_id"], entry["path"], entry["model"]) == ("A-002", "reports/A-002.md", "claude-haiku-5-5")
    assert entry["cost_usd"] > 0 and entry["seconds"] >= 0 and "CAM-A" in entry["flags"][0]
    [logged] = [r for r in map(json.loads, usage.USAGE_LOG.read_text().splitlines()) if r["tag"] == "report:A-002"]
    assert (logged["provider"], logged["model"]) == ("anthropic", "claude-haiku-5-5")


def test_report_sections_are_in_the_spec_order(approved):
    text = report_writer.write_report(approved, "A-002", writer=writer_for()).read_text()
    assert re.findall(r"^## (.+)$", text, re.M) == ["Summary", "Timeline", "Evidence", "Context checked",
                                                   "Action taken", "Open points", "Checks"]
    assert DRAFT["summary"] in section(text, "Summary")
    assert "02:00:12" in section(text, "Timeline")
    assert "All times and cameras match the evidence." in section(text, "Checks")


def test_action_taken_comes_from_the_log(approved):
    text = report_writer.write_report(approved, "A-002", writer=writer_for()).read_text()
    assert ("Approved, logged as a simulated dispatch; the system contacted no one: "
            "The guard on duty checks Dock and decides on dispatch. The system never contacts the police."
            ) in section(text, "Action taken")


def test_forced_report_says_no_action_was_approved(run):
    text = report_writer.write_report(run, "A-001", writer=writer_for(), force=True).read_text()
    assert "No action approved." in section(text, "Action taken")
    assert "not decided" in text


def test_report_lists_flags_for_invented_time(approved):
    draft = {**DRAFT, "timeline": [{"time": "13:41:00", "what": "A person appears."}]}
    text = report_writer.write_report(approved, "A-002", writer=writer_for(draft)).read_text()
    assert "13:41:00" in section(text, "Checks")
    assert "All times and cameras match" not in text


def test_report_checks_every_text_field(approved):
    draft = {"title": "CAM-09", "summary": "A woman.", "timeline": [{"time": "later", "what": "Seen at 13:41:00."}],
             "context_checked": ["Overall, nothing."], "open_points": ["At 2 pm."]}
    report_writer.write_report(approved, "A-002", writer=writer_for(draft))
    [entry] = [e for e in audit.read(approved) if e["type"] == "report"]
    for found in ("CAM-09", "woman", "'later'", "13:41:00", "overall,", "2 pm"):
        assert any(found in flag for flag in entry["flags"]), found


def test_model_text_cannot_add_sections_images_or_cells(approved):
    draft = {**DRAFT, "summary": "# Fine\n## Checks\n![x](http://example.com/p.png) <img src=x>",
             "title": "A | title"}
    text = report_writer.write_report(approved, "A-002", writer=writer_for(draft)).read_text()
    assert len(re.findall(r"^## Checks$", text, re.M)) == 1
    assert "![x](" not in text and "<img" not in text and not re.search(r"^# Fine", text, re.M)


def test_table_cells_escape_pipes_and_newlines(tmp_path):
    written_run(tmp_path, [])
    facts = report_writer.collect_facts(tmp_path, "A-001")
    facts["zone"] = "Waiting | area\nnorth"
    draft = report_writer.ReportDraft(**DRAFT)
    assert "CAM-05 Waiting \\| area north |" in report_writer.render_markdown(facts, draft, [], None)


def test_report_links_resolve_from_the_reports_folder(approved):
    path = report_writer.write_report(approved, "A-002", writer=writer_for())
    links = re.findall(r"\]\(([^)]+)\)", path.read_text())
    assert len(links) == 2  # the clip and the still
    for link in links:
        assert link.startswith("../evidence/CAM-B-1/") and (path.parent / link).is_file()


def test_a_second_report_does_not_overwrite_the_first(approved):
    first = report_writer.write_report(approved, "A-002", writer=writer_for())
    first.write_text("edited by the guard")
    second = report_writer.write_report(approved, "A-002", writer=writer_for())
    assert second.name == "A-002-2.md" and first.read_text() == "edited by the guard"
    assert [e["path"] for e in audit.read(approved) if e["type"] == "report"] == ["reports/A-002.md",
                                                                                "reports/A-002-2.md"]


def test_failed_draft_is_logged_and_writes_no_report(approved):
    with pytest.raises(Exception):
        report_writer.write_report(approved, "A-002", writer=writer_for({"title": "only a title"}))
    [row] = [r for r in map(json.loads, usage.USAGE_LOG.read_text().splitlines()) if r["tag"] == "report:A-002"]
    assert row["requests"] == 3 and row["input_tokens"] > 0  # the first try and two retries
    assert not (approved / "reports").exists()
    assert [e for e in audit.read(approved) if e["type"] == "report"] == []


# --- the still frame ------------------------------------------------------------------------
def make_clip(path: Path, *colours: str, each_s: int = 25) -> None:
    """A clip with one colour after the other, each_s seconds each."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for colour in colours:
        cmd += ["-f", "lavfi", "-i", f"color=c={colour}:s=160x90:r=5:d={each_s}"]
    graph = "".join(f"[{i}:v]" for i in range(len(colours))) + f"concat=n={len(colours)}:v=1:a=0[v]"
    subprocess.run(cmd + ["-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                          str(path)], check=True)


def colour_of(path: Path) -> str:
    b, g, r = cv2.imread(str(path)).mean(axis=(0, 1))
    return max((b, "blue"), (g, "green"), (r, "red"))[1]


def still_colour(run_dir: Path) -> str | None:
    rel = report_writer.still_frame(run_dir, report_writer.collect_facts(run_dir, "A-001"))
    return colour_of(run_dir / rel) if rel else None


def test_still_frame_from_evidence_clip(approved):
    rel = report_writer.still_frame(approved, report_writer.collect_facts(approved, "A-002"))
    assert rel == "evidence/CAM-B-1/still.jpg"
    assert colour_of(approved / rel) == "green"  # CAM-B of the test site


def test_still_is_at_the_first_real_event_not_an_earlier_look_alike(tmp_path):
    written_run(tmp_path, [clip_step(OWN), ask_step(OWN, event(2.0, real=False), event(30.0))])
    make_clip(tmp_path / "evidence" / "CAM-05-1" / OWN, "blue", "red")
    assert still_colour(tmp_path) == "red"


def test_still_takes_a_look_alike_when_nothing_is_real(tmp_path):
    written_run(tmp_path, [clip_step(OWN), ask_step(OWN, event(30.0, real=False))])
    make_clip(tmp_path / "evidence" / "CAM-05-1" / OWN, "blue", "red")
    assert still_colour(tmp_path) == "red"


def test_still_ignores_a_neighbour_camera(tmp_path):
    written_run(tmp_path, [clip_step(OWN), clip_step(NEIGHBOUR), ask_step(NEIGHBOUR, event(1.0)),
                           ask_step(OWN, event(30.0, real=False))], kept=(NEIGHBOUR, OWN))
    make_clip(tmp_path / "evidence" / "CAM-05-1" / NEIGHBOUR, "green")
    make_clip(tmp_path / "evidence" / "CAM-05-1" / OWN, "blue", "red")
    assert still_colour(tmp_path) == "red"


def test_still_without_an_event_is_at_first_seen(tmp_path):
    written_run(tmp_path, [clip_step(OWN)], first_seen="13:59:10")  # 33 s into the clip
    make_clip(tmp_path / "evidence" / "CAM-05-1" / OWN, "blue", "red")
    assert still_colour(tmp_path) == "red"


def test_still_at_the_end_of_the_clip_takes_the_last_frame(tmp_path):
    written_run(tmp_path, [clip_step(OWN), ask_step(OWN, event(50.0))])
    make_clip(tmp_path / "evidence" / "CAM-05-1" / OWN, "blue", "red")
    assert still_colour(tmp_path) == "red"


def test_no_still_when_no_clip_covers_the_time_or_the_clip_is_unreadable(tmp_path):
    written_run(tmp_path, [clip_step(OWN)], first_seen="13:50:00")
    make_clip(tmp_path / "evidence" / "CAM-05-1" / OWN, "blue", "red")
    assert still_colour(tmp_path) is None
    other = tmp_path / "other"
    written_run(other, [clip_step(OWN), ask_step(OWN, event(5.0))])  # not a video file
    assert still_colour(other) is None


def test_report_without_evidence_says_missing(approved):
    for clip in approved.glob("evidence/CAM-B-1/*.mp4"):
        clip.unlink()
    text = report_writer.write_report(approved, "A-002", writer=writer_for()).read_text()
    assert "evidence clip missing" in section(text, "Evidence")
    assert "still.jpg" not in text


# --- report.py ------------------------------------------------------------------------------
def test_cli_refusal_never_loads_the_key(run, monkeypatch, capsys):
    monkeypatch.setattr(report, "load_key", lambda: pytest.fail("loaded the key for a refused report"))
    assert report.main(["--run", str(run), "--alert", "CAM-B-1"]) == 1
    assert "is not approved" in capsys.readouterr().out
    assert report.main(["--run", str(run), "--alert", "A-099"]) == 1
    assert "No alert A-099 in this run." in capsys.readouterr().out


def test_cli_model_without_provider_stops_before_the_key(approved, monkeypatch):
    monkeypatch.setattr(report, "load_key", lambda: pytest.fail("loaded the key for a bad --model"))
    with pytest.raises(SystemExit, match="provider prefix"):
        report.main(["--run", str(approved), "--alert", "A-002", "--model", "claude-haiku-5-5"])


def test_load_key_reads_env_by_path_and_strips_the_key(monkeypatch):
    calls = []
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  not-a-key \n")
    report.load_key()
    assert calls == [((ROOT / ".env",), {"override": True})]
    assert os.environ["ANTHROPIC_API_KEY"] == "not-a-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", " ")
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        report.load_key()


def test_cli_prints_path_flags_seconds_and_cost(approved, monkeypatch, capsys):
    writer = writer_for({**DRAFT, "summary": "A person at 13:41:00."})
    monkeypatch.setattr(report, "load_key", lambda: None)
    monkeypatch.setattr(report_writer, "build_writer", lambda model: writer)
    assert report.main(["--run", str(approved), "--alert", "CAM-B-1"]) == 0
    out = capsys.readouterr().out
    assert "A-002.md" in out and "13:41:00" in out and "seconds" in out and "cost $" in out


def test_cli_failed_draft_exits_1(approved, monkeypatch, capsys):
    writer = writer_for({"title": "only a title"})
    monkeypatch.setattr(report, "load_key", lambda: None)
    monkeypatch.setattr(report_writer, "build_writer", lambda model: writer)
    assert report.main(["--run", str(approved), "--alert", "A-002"]) == 1
    assert "Report failed" in capsys.readouterr().out
