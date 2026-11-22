"""Incident reports for reviewed alerts (task D5).

Facts are collected in code from the run folder, and a checker compares any report text with them.

- A fact time comes only from structured fields: the alert's times, the clip windows, the video
  events and the context queries and rows. Times inside free text (the agent's reason, a video
  answer, a guard's note) are claims, so the checker does not accept them.
- A clip's camera and start come from its file name, which the recorder writes after clamping the
  window to the recording. get_clip's result only repeats the window that was asked for.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from agentlab import audit
from agentlab.review import find_alert
from agentlab.triage_agent import evidence_from_trace
from fakecctv.alerts import AlertStore

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
