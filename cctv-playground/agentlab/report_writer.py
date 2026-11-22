"""Incident reports for reviewed alerts (task D5).

Facts are collected in code from the run folder, Haiku drafts the text from them, a checker
compares the text with them, and code renders the markdown.

- A fact time comes only from structured fields: the alert's times, the clip windows, the video
  events and the context queries and rows. Times inside free text (the agent's reason, a video
  answer, a guard's note) are claims, so the checker does not accept them.
- A clip's camera and start come from its file name, which the recorder writes after clamping the
  window to the recording. get_clip's result only repeats the window that was asked for.
- The header table and "Action taken" are written by code: an approval is a simulated dispatch, and
  a model would report it as done.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

import pydantic_ai
from pydantic import BaseModel
from pydantic_ai import Agent, ModelResponse, UsageLimits, capture_run_messages
from pydantic_ai.models import Model

from agentlab import audit
from agentlab.review import decided_line, find_alert, one_line
from agentlab.triage_agent import evidence_from_trace
from agentlab.usage import log_call
from fakecctv.alerts import AlertStore

pydantic_ai.BANNER_ENABLED = False  # keep report.py's output clean

REPORT_MODEL = "anthropic:claude-haiku-5-5"
TEMPLATE = Path(__file__).resolve().parents[1] / "context" / "report_template.md"
REQUEST_LIMIT = 3  # the first try and two retries
TOLERANCE_S = 2
DAY_S = 24 * 3600
GENDER_AGE_WORDS = (
    "man", "men", "woman", "women", "male", "males", "female", "females", "boy", "boys", "girl", "girls",
    "lady", "ladies", "gentleman", "gentlemen", "guy", "guys", "he", "she", "him", "her", "his", "hers",
    "elderly", "young", "teenager", "teenagers", "child", "children", "kid", "kids",
)
FILLER_PHRASES = ("it is worth noting", "it should be noted", "it appears that", "in conclusion", "overall,",
                  "notably", "seamless", "robust", "delve")

# The recorder's file names: CAM_YYYYmmdd-HHMMSS_HHMMSS.mp4 (clip), CAM_YYYYmmdd-HHMMSS.jpg (frame).
EVIDENCE_NAME = re.compile(r"^(?P<camera>.+)_(?P<start>\d{8}-\d{6})(?:_(?P<end>\d{6}))?\.(?:mp4|jpg)$")
AM_PM = re.compile(r"(?<![\w:])\d{1,2}(?:[:.]\d\d){0,2}\s*(?:[ap]m\b|[ap]\.m\.)", re.I)
# Not inside a longer time: 13:58:59 is one time, never also 13:58 or 58:59.
SITE_TIME = re.compile(r"(?<!\d)(?<!\d:)(\d{1,2}):(\d\d)(?::(\d\d))?(?!\d)(?!:\d)")
CAMERA_ID = re.compile(r"\bCAM-[A-Z0-9]+", re.I)
GENDER_AGE = re.compile(rf"\b(?:{'|'.join(GENDER_AGE_WORDS)})\b", re.I)

# What neutral() replaces in the text the writer gets. Pronouns are left to the checker.
ONE_PERSON = ("man", "woman", "male", "female", "boy", "girl", "lady", "gentleman", "guy", "teenager", "child", "kid")
PEOPLE = ("men", "women", "males", "females", "boys", "girls", "ladies", "gentlemen", "guys", "teenagers",
          "children", "kids")
PERSON_NOUN = re.compile(rf"\b(?:{'|'.join(ONE_PERSON + PEOPLE)})\b", re.I)
PERSON_ADJECTIVE = re.compile(
    rf"\b(?:young|elderly|male|female)\s+(?=(?:{'|'.join(ONE_PERSON + PEOPLE)}|person|people)\b)", re.I)


# --- facts ----------------------------------------------------------------------------------
def _clock(value) -> str | None:
    """HH:MM:SS from a site time as the tools take it: 13:58, 13:58:57 or an ISO timestamp."""
    text = str(value).strip().split("T")[-1]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    return None


def _later(time: str, than: str) -> bool:
    """time is after `than`, reading the shorter way round midnight."""
    return 0 < (_seconds(time) - _seconds(than)) % DAY_S < DAY_S / 2


def _recording(path: str) -> dict | None:
    """Camera, real start and end of a clip (or a frame's camera and time), from its file name."""
    name = PurePosixPath(str(path)).name
    match = EVIDENCE_NAME.match(name)
    if not match:
        return None
    start = datetime.strptime(match["start"], "%Y%m%d-%H%M%S")
    end = datetime.strptime(match["end"], "%H%M%S").strftime("%H:%M:%S") if match["end"] else None
    return {"name": name, "camera": match["camera"].upper(), "start": start, "end": end}


def _video_events(cid: str, trace: list[dict]) -> list[dict]:
    """Every event of every successful video check, in the order the agent got them."""
    events = []
    for step in trace:
        if not step.get("ok") or step["tool"] not in ("ask_video", "second_look"):
            continue
        result = step["result"]
        path = step["args"].get("clip_path") if step["tool"] == "ask_video" else result.get("clip_path")
        clip = _recording(path)
        if not clip:
            continue
        for e in result.get("events") or []:
            events.append({
                "time": f"{clip['start'] + timedelta(seconds=e['start_s']):%H:%M:%S}",
                "end": f"{clip['start'] + timedelta(seconds=e['end_s']):%H:%M:%S}",
                "type": e["event_type"], "real": e["real"], "what": e.get("reason", ""),
                "model": result.get("model"), "camera": clip["camera"],
                "clip": f"evidence/{cid}/{clip['name']}", "offset_s": e["start_s"],
            })
    return events


def _context(trace: list[dict], created: str) -> tuple[list[dict], set[str]]:
    """The badge-log and roster lookups as facts (an empty one is a fact too), and their times.

    The agent typed the query times. A badge window that ends before it starts looked at nothing,
    so it is no fact, and a roster question about a time after the alert gives no fact time."""
    facts: list[dict] = []
    times: set[str | None] = set()

    def add(source: str, time: str | None, text: str) -> None:
        fact = {"source": source, "time": time, "text": text}
        if fact not in facts:
            facts.append(fact)

    for step in trace:
        if not step.get("ok") or step["tool"] not in ("access_log", "roster"):
            continue
        args, rows = step["args"], step["result"].get("rows", [])
        count = step["result"].get("count", len(rows))
        if step["tool"] == "access_log":
            start, end = _clock(args["start"]), _clock(args["end"])
            if not start or not end or _later(start, end):
                continue
            times |= {start, end}
            where = f"at {args['door']}" if args.get("door") else "at any door"
            window = f"{start} to {end} {where}"
            for r in rows:
                at = _clock(r.get("time"))
                times.add(at)
                add("access_log", at, f"{at} {r.get('door', '')}: badge {r.get('badge', '')}, "
                                      f"{r.get('holder', '')}, {r.get('result', '')}")
            if not rows:
                add("access_log", end, f"No badge-log entries {window}")
            elif count > len(rows):
                add("access_log", end, f"Only {len(rows)} of {count} badge-log entries {window} are listed")
        else:
            at = _clock(args["at"])
            if at and not _later(at, created):
                times.add(at)
            for r in rows:
                start, end = _clock(r.get("start")), _clock(r.get("end"))
                times |= {start, end}
                note = f". {r['note']}" if r.get("note") else ""
                add("roster", start, f"Roster {r.get('start', '')} to {r.get('end', '')}: {r.get('who', '')}, "
                                     f"{r.get('role', '')}, zones {r.get('zones', '')}{note}")
            if not rows:
                add("roster", at, f"Nobody on the roster at {at}")
            elif count > len(rows):
                add("roster", at, f"Only {len(rows)} of {count} roster entries at {at} are listed")
    return facts, {t for t in times if t}


def collect_facts(run_dir: Path, ref: str) -> dict:
    run_dir = Path(run_dir)
    alerts = AlertStore(run_dir).all()
    alert = find_alert(alerts, ref)
    cand, cid = alert["candidate"], alert["candidate"]["candidate_id"]
    run_file = run_dir / f"{cid}.json"
    trace = json.loads(run_file.read_text(encoding="utf-8"))["trace"] if run_file.is_file() else alert["trace"]

    mine = {e["type"]: e for e in audit.read(run_dir) if e.get("alert_id") == alert["id"]}
    produced = evidence_from_trace(trace)  # what the tools made, whether or not a copy was kept
    recordings = [r for r in map(_recording, produced) if r]
    expected = dict.fromkeys([*alert["evidence"],
                              *(f"evidence/{cid}/{PurePosixPath(p).name}" for p in produced)])
    present = [p for p in expected if (run_dir / p).is_file()]

    linked = None
    if alert.get("linked_to"):
        for other in alerts:
            if other["id"] == alert["linked_to"]:
                linked = {"id": other["id"], "camera": other["candidate"]["camera_id"],
                          "first_seen": _clock(other["candidate"]["first_seen"])}

    first_seen, detected, created = (_clock(v) for v in (cand["first_seen"], cand["detected_at"], alert["created"]))
    events = _video_events(cid, trace)
    context, times = _context(trace, created)
    times |= {first_seen, detected, created}
    times |= {f"{r['start']:%H:%M:%S}" for r in recordings} | {r["end"] for r in recordings if r["end"]}
    times |= {e[k] for e in events for k in ("time", "end")}
    cameras = {cand["camera_id"].upper()} | {r["camera"] for r in recordings} | {e["camera"] for e in events}
    if linked:
        times.add(linked["first_seen"])
        cameras.add(linked["camera"].upper())

    return {
        "site": mine.get("verdict", {}).get("site", ""),
        "alert_id": alert["id"], "candidate_id": cid,
        "camera": cand["camera_id"], "zone": cand["zone"], "kind": cand["kind"],
        "first_seen": first_seen, "detected_at": detected, "created": created,
        "verdict": alert["verdict"], "priority": alert["priority"], "reason": alert["reason"],
        "linked_to": alert.get("linked_to"), "linked_alert": linked,
        "evidence": present, "evidence_missing": [p for p in expected if p not in present],
        "video_events": events, "context": context,
        "decision": mine.get("decision"), "action": mine.get("action", {}).get("action"),
        "cameras": sorted(cameras),
        "fact_times": sorted(t for t in times if t),
    }


# --- the checker ----------------------------------------------------------------------------
def _seconds(hms: str) -> int:
    h, m, s = map(int, hms.split(":"))
    return 3600 * h + 60 * m + s


def _matches(match: re.Match, fact_times: list[str]) -> bool:
    """HH:MM:SS within the tolerance of a fact time; HH:MM in the same minute as one."""
    h, m, s = int(match[1]), int(match[2]), int(match[3] or 0)
    if h > 23 or m > 59 or s > 59:
        return False
    if match[3] is None:
        return any(t.startswith(f"{h:02d}:{m:02d}:") for t in fact_times)
    gaps = (abs(3600 * h + 60 * m + s - _seconds(t)) for t in fact_times)
    return any(min(gap, DAY_S - gap) <= TOLERANCE_S for gap in gaps)


def check_report(texts: list[str], facts: dict, timeline_times: list[str] | tuple[str, ...] = ()) -> list[str]:
    """One sentence per problem found. timeline_times are the timeline's time fields: each must be
    a site time, on top of matching the facts like any time in the text."""
    flags: list[str] = []
    not_site_format = "time not in site format (HH:MM:SS):"

    def check_times(text: str) -> None:
        for found in AM_PM.finditer(text):
            flags.append(f"{not_site_format} {found[0]!r}.")
        for found in SITE_TIME.finditer(AM_PM.sub(" ", text)):  # an am/pm time is flagged once
            if not _matches(found, facts["fact_times"]):
                flags.append(f"Time {found[0]} is not in the evidence.")

    for time in timeline_times:
        if SITE_TIME.fullmatch(time.strip()):
            check_times(time)
        else:
            flags.append(f"{not_site_format} {time!r}.")

    text = "\n".join(texts)
    check_times(text)
    cameras = {c.upper() for c in facts["cameras"]}
    for found in CAMERA_ID.finditer(text):
        if found[0].upper() not in cameras:
            flags.append(f"Camera {found[0]} is not in the evidence.")
    for found in GENDER_AGE.finditer(text):
        flags.append(f"The word {found[0]!r} describes gender or age.")
    for phrase in FILLER_PHRASES:
        end = r"\b" if phrase[-1].isalnum() else ""
        if re.search(rf"\b{re.escape(phrase)}{end}", text, re.I):
            flags.append(f"filler phrase: {phrase!r}.")
    return list(dict.fromkeys(flags))


# --- the draft ------------------------------------------------------------------------------
class TimelineEntry(BaseModel):
    time: str
    what: str


class ReportDraft(BaseModel):
    """What the model writes. The header and the action taken are not in it: code writes those."""
    title: str
    summary: str
    timeline: list[TimelineEntry]
    context_checked: list[str]
    open_points: list[str]


INSTRUCTIONS = f"""\
You draft a site incident report for a security guard to check and sign. You get the facts as JSON.

- Use only the facts given. Do not guess beyond them: anything unknown goes under Open points.
- Take times only from fact_times, written as HH:MM:SS. agent_reason, the "what" of a video event
  and the guard's reason are free text: never take a time from them. Seconds in them, such as
  "21.6 s", count from the start of a clip, so leave them out.
- Write "a person". Never mention gender, age or ethnicity, and no he or she. Do not identify
  people. Mention clothing only where it is needed to tell events apart.
- title: a few plain words on what happened and where.
- summary: 2 to 4 short sentences in plain words: what happened, where, when and what was decided.
- An approved action is only approved, not carried out. Never write that someone was sent, went,
  checked, cleared or was contacted. With no approved action, do not mention one.
- timeline: each line is one event at one site time. "time" holds only that time, as HH:MM:SS.
- context_checked: what the badge log and the roster showed, including that they showed nothing.
- open_points: what is still unknown.
- No filler, hedging or praise. Never use these phrases: {"; ".join(FILLER_PHRASES)}
"""


def build_writer(model: str | Model = REPORT_MODEL) -> Agent[None, ReportDraft]:
    # defer_model_check: no key is needed until the first request. No sampling settings:
    # claude-haiku-5-5 rejects them.
    return Agent(model, output_type=ReportDraft, instructions=INSTRUCTIONS, retries=2, defer_model_check=True)


def neutral(text: str) -> str:
    """Gender and age nouns become "person" or "people"."""
    def replace(found: re.Match) -> str:
        word = "people" if found[0].lower() in PEOPLE else "person"
        return word.capitalize() if found[0][0].isupper() else word

    text = re.sub(r"\b([Aa])n (?=elderly\b)", r"\1 ", text)
    return PERSON_NOUN.sub(replace, PERSON_ADJECTIVE.sub("", text))


def writer_input(facts: dict) -> str:
    """The facts as the writer gets them: free text neutralised, no real-clock times, no file paths."""
    decision = facts["decision"]
    given = {
        **{k: facts[k] for k in ("site", "alert_id", "camera", "zone", "kind", "first_seen", "detected_at",
                                 "created", "verdict", "priority", "linked_alert")},
        "agent_reason": neutral(facts["reason"]),
        "video_events": [{**{k: e[k] for k in ("time", "end", "camera", "type", "real")}, "what": neutral(e["what"])}
                         for e in facts["video_events"]],
        "context": [{**c, "text": neutral(c["text"])} for c in facts["context"]],
        "decision": {"decision": decision["decision"], "reason": neutral(decision["reason"])} if decision else None,
        "approved_action_not_carried_out": facts["action"],
        "fact_times": facts["fact_times"],
    }
    return "Draft the incident report from these facts.\n\n" + json.dumps(given, indent=1)


# --- the still frame ------------------------------------------------------------------------
def still_point(facts: dict) -> tuple[str, float, str] | None:
    """(clip, seconds into it, site time) of the still, on the alert's own camera: the start of the
    first event of the alert's type (a real one before a look-alike), else the first-seen time."""
    camera = facts["camera"].upper()
    events = [e for e in facts["video_events"] if e["camera"] == camera and e["type"] == facts["kind"]]
    event = next((e for e in events if e["real"]), events[0] if events else None)
    if event and event["clip"] in facts["evidence"]:
        return event["clip"], event["offset_s"], event["time"]

    at = event["time"] if event else facts["first_seen"]
    for path in facts["evidence"]:
        clip = _recording(path)
        if not clip or clip["camera"] != camera or not clip["end"]:
            continue
        start = _seconds(f"{clip['start']:%H:%M:%S}")
        offset = (_seconds(at) - start) % DAY_S
        if offset <= (_seconds(clip["end"]) - start) % DAY_S:
            return path, offset, at
    return None


def still_frame(run_dir: Path, facts: dict) -> str | None:
    point = still_point(facts)
    if not point:
        return None
    clip, offset, _ = point
    rel = f"evidence/{facts['candidate_id']}/still.jpg"
    source = str(Path(run_dir) / clip)
    with tempfile.TemporaryDirectory(prefix="fakecctv-still-") as work:
        out = Path(work) / "still.jpg"
        # A seek past the last decodable frame writes nothing, so then take the last frame.
        for where, extra in ((["-ss", f"{offset:.2f}"], ["-frames:v", "1"]), (["-sseof", "-1"], [])):
            done = subprocess.run(["ffmpeg", "-y", "-v", "error", *where, "-i", source, *extra,
                                   "-update", "1", "-q:v", "3", str(out)], capture_output=True)
            if done.returncode == 0 and out.is_file():
                shutil.copyfile(out, Path(run_dir) / rel)
                return rel
    return None


# --- the markdown ---------------------------------------------------------------------------
def _md(text: str) -> str:
    """One line of plain text: it cannot open a section, an image, a link or HTML."""
    line = one_line(text).replace("<", "&lt;").replace("[", "\\[")
    return f"\\{line}" if line.startswith("#") else line


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) or "- none"


def render_markdown(facts: dict, draft: ReportDraft, flags: list[str], still: str | None) -> str:
    def cell(text: str) -> str:
        return _md(text).replace("|", "\\|")

    decision, decided = facts["decision"], "not decided"
    if decision:
        decided = f"{decision['decision']} by {decision['reviewer']}, {decided_line(decision, facts['first_seen'])}"

    evidence = [f"[{PurePosixPath(p).name}](../{p})" for p in facts["evidence"]]
    evidence += [f"evidence clip missing: {PurePosixPath(p).name}" for p in facts["evidence_missing"]]
    evidence_block = _bullets(evidence or ["evidence clip missing"])
    if still:
        point = still_point(facts)
        at = f" at {point[2]}" if point else ""
        evidence_block += f"\n\n![Still frame from {facts['camera']}{at}](../{still})"

    action = "No action approved."
    if facts["action"]:
        action = ("Approved, logged as a simulated dispatch; the system contacted no one: "
                  f"{_md(facts['action'])}")

    verdict = facts["verdict"]
    if verdict == "linked":
        verdict += f" to {facts['linked_to']}"

    return TEMPLATE.read_text(encoding="utf-8").format(
        alert_id=facts["alert_id"], title=_md(draft.title),
        incident_id=cell(f"{facts['alert_id']} ({facts['candidate_id']})"),
        site=cell(facts["site"]), camera_zone=cell(f"{facts['camera']} {facts['zone']}"),
        kind=cell(facts["kind"]), first_seen=cell(facts["first_seen"]), priority=cell(facts["priority"]),
        verdict=cell(verdict), decision=cell(decided),
        summary=_md(draft.summary),
        timeline=_bullets([f"{_md(t.time)}: {_md(t.what)}" for t in draft.timeline]),
        evidence=evidence_block,
        context_checked=_bullets([_md(c) for c in draft.context_checked]),
        action_taken=action,
        open_points=_bullets([_md(o) for o in draft.open_points]),
        checks=_bullets([_md(f) for f in flags]) if flags else "All times and cameras match the evidence.",
    )


# --- the report -----------------------------------------------------------------------------
def require_approved(facts: dict, force: bool = False) -> None:
    if not force and (facts["decision"] or {}).get("decision") != "approve":
        raise ValueError(f"{facts['alert_id']} is not approved; approve it in review.py first, or use --force.")


def write_report(run_dir: Path, ref: str, *, writer: Agent[None, ReportDraft] | None = None,
                 model: str = REPORT_MODEL, force: bool = False) -> Path:
    run_dir = Path(run_dir)
    facts = collect_facts(run_dir, ref)
    require_approved(facts, force)
    writer = writer or build_writer(model)
    model_id = model.split(":", 1)[-1]

    started = time.perf_counter()
    with capture_run_messages() as messages:
        try:
            draft = writer.run_sync(writer_input(facts), usage_limits=UsageLimits(request_limit=REQUEST_LIMIT)).output
        finally:  # from the messages, so a failed draft is logged too
            replies = [m for m in messages if isinstance(m, ModelResponse)]
            row = log_call(provider="anthropic", model=model_id,
                           input_tokens=sum(m.usage.input_tokens or 0 for m in replies),
                           output_tokens=sum(m.usage.output_tokens or 0 for m in replies),
                           seconds=time.perf_counter() - started, tag=f"report:{facts['alert_id']}",
                           extra={"requests": len(replies)})

    flags = check_report([draft.title, draft.summary, *(t.what for t in draft.timeline), *draft.context_checked,
                          *draft.open_points], facts, timeline_times=[t.time for t in draft.timeline])
    text = render_markdown(facts, draft, flags, still_frame(run_dir, facts))

    folder = run_dir / "reports"
    folder.mkdir(exist_ok=True)
    path, n = folder / f"{facts['alert_id']}.md", 1
    while path.exists():  # never over a report that a guard may have edited
        n += 1
        path = folder / f"{facts['alert_id']}-{n}.md"
    path.write_text(text, encoding="utf-8")
    audit.append(run_dir, {"type": "report", "alert_id": facts["alert_id"],
                           "path": path.relative_to(run_dir).as_posix(), "model": model_id,
                           "cost_usd": row["cost_usd"], "seconds": row["seconds"], "flags": flags})
    return path
