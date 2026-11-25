"""person_on_floor: measured facts and doubt signals about a person on the floor (rules in floor_rules.json).

The system describes, it does not decide. For each person_on_floor candidate seen by Perception, the code asks
Perception a neutral posture question on a dense frame sample (the close check, or probe), follows the person while
they stay on the floor (follow-ups) and measures the facts itself: how the person reached the floor, posture on the
floor, time on the floor and what came next. It then computes objective doubt signals (floor_rules.json
"doubt_signals"). Every incident goes to the guard; one with at least one signal is marked "Look closely".
Thresholds only decide whether a signal is shown, never what happened. A separate model call may give a one-sentence
"System's assessment" from the timed postures; it is shown as an unverified opinion and changes nothing.

The model calls are injected (`ask(times_us, phase)`, `ask_assessment(prompt)`); everything else is deterministic.
"""
from __future__ import annotations

import json
import re
from math import hypot
from pathlib import Path
from statistics import median

RULES = json.loads(Path(__file__).with_name("floor_rules.json").read_text())
FLOOR_CATEGORY = "person_on_floor"
LEGACY_CATEGORIES = ("person_fell",)  # archived runs: same candidate, older wording
# Only the current category starts a check; archived person_fell observations are read as they were recorded.
CANDIDATE_CATEGORIES = (FLOOR_CATEGORY,)
US = 1_000_000
LOOK_CLOSELY, NO_DOUBT_SIGNAL = "look_closely", "no_doubt_signal"

PROMPT = (
    "For each image, list every person you can see. For each person give: id, a label P1, P2, ... that stays "
    "the same for the same person in all images; posture, exactly one of: {vocabulary}; x and y, the approximate "
    "centre of the person as fractions of the image width and height, from 0 to 1; w and h, the approximate width "
    "and height of a box around the person, as fractions of the image width and height; seat_nearby, true when a "
    "chair, bench or other seat touches the person or is right next to them, otherwise false. Use sitting_on_seat "
    "for a person sitting on a chair, bench or other seat, and sitting_on_floor only when the person sits directly "
    "on the floor. Report only what is visible in each image. Return an empty list for an image with nobody visible."
)


def prompt(rules=RULES):
    return PROMPT.format(vocabulary=", ".join(rules["vocabulary"]))


# ---------- sampling ----------

def probe_times(anchor_us, duration_us, rules=RULES):
    p = rules["probe"]
    times = [anchor_us + round((p["before"]["first_offset_s"] + i * p["before"]["step_s"]) * US) for i in range(p["before"]["count"])]
    times += [anchor_us + round((p["after"]["first_offset_s"] + i * p["after"]["step_s"]) * US) for i in range(p["after"]["count"])]
    return [t for t in times if 0 <= t < duration_us]


def followup_times(last_us, duration_us, rules=RULES):
    f = rules["followup"]
    times = [last_us + round((f["first_offset_s"] + i * f["step_s"]) * US) for i in range(f["count"])]
    return [t for t in times if 0 <= t < duration_us]


# ---------- candidates ----------

def is_candidate(observation):
    return (observation.category in CANDIDATE_CATEGORIES
            or getattr(observation, "possible_category", None) in CANDIDATE_CATEGORIES)


def is_claim(observation):
    """The first look reported the person on the floor (not only suspected it)."""
    return observation.category in CANDIDATE_CATEGORIES + LEGACY_CATEGORIES


def anchor_us(finding):
    frames = finding.citation.frames
    return min(f.source_time_us for f in frames) if frames else finding.citation.interval.start_us


# ---------- facts from one person's sequence ----------

def _distance(a, b, aspect):
    return hypot(a[0] - b[0], (a[1] - b[1]) * aspect)


_BOX = ("w", "h", "seat_nearby")


def _entry(s):
    t, posture, x, y, source, *extra = s
    out = {"t_us": t, "posture": posture, "source": source}
    if x is not None:
        out.update(x=x, y=y)
        out.update({k: v for k, v in (extra[0] if extra else {}).items() if k in _BOX})
    return out


def describe(seq, anchor, *, aspect, video_end_us, followup_stopped=False, rules=RULES):
    """Facts for one person's sequence [(t_us, posture, x, y, source[, {w, h, seat_nearby}])], source 'probe' or
    'followup'. Returns the measured facts and `seen`, what the close check saw for this person:
    on_floor, on_floor_not_near_report, kneeling, seated, no_floor, upright_throughout or no_person.
    Times are integer microseconds. No threshold here decides anything.
    """
    upright, floor = set(rules["upright"]), set(rules["on_floor"])
    labels = [s[1] for s in seq]
    visible = [l for l in labels if l != "not_visible"]
    base = {"sequence": [_entry(s) for s in seq]}
    if not any(l in floor for l in labels):
        if not visible:
            seen = "no_person"
        elif all(l in upright for l in visible):
            seen = "upright_throughout"
        elif "kneeling" in visible:
            seen = "kneeling"
        elif "sitting_on_seat" in visible:
            seen = "seated"
        else:
            seen = "no_floor"
        return {**base, "seen": seen}
    j = next(i for i, l in enumerate(labels) if l in floor)
    ups = [i for i in range(j) if labels[i] in upright]
    if ups:
        i = ups[-1]
        between = [labels[k] for k in range(i + 1, j) if labels[k] != "not_visible"]
        arrival = {"observed": True, "upright_us": seq[i][0], "seconds": round((seq[j][0] - seq[i][0]) / US, 2),
                   "via": list(dict.fromkeys(between))}
    else:
        arrival = {"observed": False, "why": "already_on_floor" if not any(l != "not_visible" for l in labels[:j])
                   or labels[0] in floor else "not_seen_upright",
                   "earlier_postures": list(dict.fromkeys(l for l in labels[:j] if l != "not_visible"))}
    end, glitches, k = j, 0, j + 1
    while k < len(seq):
        if labels[k] in floor:
            end, glitches = k, 0
        elif labels[k] in upright:
            break
        else:
            glitches += 1
            if glitches > rules["max_glitch_frames_in_floor_run"]:
                break
        k += 1
    first_us, until_us = seq[j][0], seq[end][0]
    segments = []
    for t, p, *_ in seq[j:end + 1]:
        if p in floor and (not segments or segments[-1]["posture"] != p):
            segments.append({"posture": p, "from_us": t})
    after = seq[end + 1:]
    stood = next((n for n, s in enumerate(after) if s[1] in upright), None)
    if stood is not None:
        via = list(dict.fromkeys(s[1] for s in after[:stood] if s[1] != "not_visible"))
        outcome = {"kind": "stood_up", "at_us": after[stood][0], "via": via}
    elif after:
        outcome = {"kind": "last_seen", "at_us": after[-1][0], "posture": after[-1][1]}
    elif until_us >= video_end_us - round(rules["followup"]["step_s"] * US) - 1:
        outcome = {"kind": "on_floor_at_end", "at_us": until_us}
    else:
        outcome = {"kind": "followup_stopped" if followup_stopped else "observation_ended", "at_us": until_us}
    window = [s for s in seq[j:end + 1] if s[1] in floor and s[0] <= first_us + rules["min_floor_s"] * US]
    moved = max(_distance((window[0][2], window[0][3]), (s[2], s[3]), aspect) for s in window)
    corroborated = any(s[4] == "followup" and s[1] in floor for s in seq[j:end + 1])
    lo, hi = rules["near_candidate_s"]
    near = lo * US <= first_us - anchor <= hi * US
    return {**base, "seen": "on_floor" if near else "on_floor_not_near_report",
            "first_floor_us": first_us, "floor_until_us": until_us,
            "floor_seconds": round((until_us - first_us) / US, 2), "floor_postures": segments,
            "arrival": arrival, "outcome": outcome, "max_displacement": round(moved, 4),
            "followup_still_on_floor": corroborated}


# Which person of a close check the incident is about: someone on the floor at the reported moment first.
_RANK = ["on_floor", "on_floor_not_near_report", "kneeling", "seated", "no_floor", "upright_throughout", "no_person"]


def _rank(facts):
    return _RANK.index(facts["seen"])


# ---------- orchestration: probe, follow-ups, merging, budget ----------

def _extra(p):
    return {k: p[k] for k in _BOX if k in p}


def _tracks(frames):
    """{id: [(t_us, posture, x, y, extra)]} from one call's frames, missing persons as not_visible."""
    ids = list(dict.fromkeys(p["id"] for f in frames for p in f["persons"]))
    out = {pid: [] for pid in ids}
    for f in frames:
        seen = {p["id"]: p for p in f["persons"]}
        for pid in ids:
            p = seen.get(pid)
            out[pid].append((f["t_us"], p["posture"], p["x"], p["y"], _extra(p)) if p
                            else (f["t_us"], "not_visible", None, None, {}))
    return out


def _linked(frames, last_xy, aspect, rules):
    """The person nearest the last known position in each follow-up frame, or not_visible."""
    limit = rules["followup"]["link_max_distance"]
    out = []
    for f in frames:
        near = [(_distance((p["x"], p["y"]), last_xy, aspect), p) for p in f["persons"]]
        near = [n for n in near if n[0] <= limit]
        if near:
            p = min(near, key=lambda n: n[0])[1]
            out.append((f["t_us"], p["posture"], p["x"], p["y"], "followup", _extra(p)))
            last_xy = (p["x"], p["y"])
        else:
            out.append((f["t_us"], "not_visible", None, None, "followup", {}))
    return out


def _still_on_floor(seq, rules):
    tail = [s for s in seq if s[1] != "not_visible"]
    return bool(tail) and tail[-1][1] in rules["on_floor"]


def check(candidates, ask, *, duration_us, aspect, frame_size=None, claimed=None, rules=RULES):
    """Incidents for person_on_floor candidates, each with its facts, doubt signals and status.

    candidates: [(observation_id, anchor_us)]. claimed: the observation ids the first look reported on the floor
    (the others were only suspected); None means all were reported. frame_size: (width, height) in pixels, used to
    show sizes and image-edge distances. ask(times_us, phase) -> (inspection_id, frames) where frames is
    [{"t_us", "display_index", "frame_id", "persons": [{"id", "posture", "x", "y"[, "w", "h", "seat_nearby"]}]}],
    or raises an exception carrying the failure text. Returns a list of incident dicts.
    """
    incidents, used = [], 0
    gap = round(rules["merge_gap_s"] * US)
    for observation_id, anchor in sorted(candidates, key=lambda c: (c[1], c[0])):
        # Merge only into time someone was actually seen on the floor at the reported moment; a report near a
        # check that found nobody on the floor gets its own check.
        home = next((i for i in incidents if i.get("seen") == "on_floor"
                     and i["span_us"][0] - gap <= anchor <= i["span_us"][1] + gap), None)
        if home is not None:
            home["observation_ids"].append(observation_id)
            continue
        incident = {"observation_ids": [observation_id], "anchor_us": anchor, "inspections": [], "frames": []}
        incidents.append(incident)
        if used >= rules["max_inspections_per_video"]:
            incident.update(seen="budget_exhausted", span_us=[anchor, anchor], sequence=[])
            continue
        times = probe_times(anchor, duration_us, rules)
        used += 1
        try:
            inspection_id, frames = ask(times, "floor_probe")
        except Exception as exc:  # noqa: BLE001 - a failed probe still goes to the guard
            incident.update(seen="probe_failed", error=str(exc), span_us=[anchor, anchor], sequence=[])
            continue
        incident["inspections"].append(inspection_id)
        incident["frames"].extend(frames)
        people = []
        for pid, track in _tracks(frames).items():
            seq = [(t, p, x, y, "probe", e) for t, p, x, y, e in track]
            people.append((pid, seq, describe(seq, anchor, aspect=aspect, video_end_us=duration_us, rules=rules)))
        if not people:
            incident.update(seen="no_person", span_us=[anchor, times[-1] if times else anchor], sequence=[])
            continue
        pid, seq, facts = min(people, key=lambda p: (_rank(p[2]), p[0]))
        followups, stopped = 0, False
        while facts.get("first_floor_us") is not None and _still_on_floor(seq, rules):
            last = next(s for s in reversed(seq) if s[1] != "not_visible")
            times = followup_times(seq[-1][0], duration_us, rules)
            if not times:
                break
            if followups >= rules["followup"]["max_per_incident"] or used >= rules["max_inspections_per_video"]:
                stopped = True
                break
            used += 1
            followups += 1
            try:
                inspection_id, frames = ask(times, "floor_followup")
            except Exception as exc:  # noqa: BLE001
                incident.setdefault("followup_errors", []).append(str(exc))
                stopped = True
                break
            incident["inspections"].append(inspection_id)
            incident["frames"].extend(frames)
            seq = seq + _linked(frames, (last[2], last[3]), aspect, rules)
            facts = describe(seq, anchor, aspect=aspect, video_end_us=duration_us, rules=rules)
        facts = describe(seq, anchor, aspect=aspect, video_end_us=duration_us, followup_stopped=stopped, rules=rules)
        incident.update(person=pid, **facts)
        # Later reports merge only into time actually spent on the floor, never into a window where nobody was down.
        incident["span_us"] = ([facts["first_floor_us"], facts["floor_until_us"]] if facts.get("first_floor_us") is not None
                               else [anchor, anchor])
    for incident in incidents:
        first_look = "reported" if claimed is None or any(o in claimed for o in incident["observation_ids"]) else "suspected"
        mark(incident, first_look=first_look, frame_size=frame_size, aspect=aspect, rules=rules)
    return incidents


# ---------- doubt signals (shown to the guard, never a decision) ----------

_LEGACY_SEEN = {"verified": "on_floor", "moving_on_floor": "on_floor", "floor_too_short": "on_floor",
                "not_corroborated": "on_floor", "not_near_candidate": "on_floor_not_near_report",
                "kneeling_only": "kneeling", "seated_only": "seated"}


def seen_of(incident):
    """What the close check saw; also reads incidents stored before rules v3 (status verified / to_review)."""
    if "seen" in incident:
        return incident["seen"]
    if incident.get("status") == "verified":
        return "on_floor"
    reason = incident.get("reason")
    return _LEGACY_SEEN.get(reason, reason or "no_person")


def floor_seen(incident):
    return incident.get("first_floor_us") is not None


def _signal(code, value=None):
    return {"code": code, "value": value}


def doubt_signals(incident, *, first_look, frame_size=None, aspect, rules=RULES):
    """Objective doubt signals of one incident, each {"code", "value"} with the measured value (floor_rules.json)."""
    D, floor = rules["doubt_signals"], set(rules["on_floor"])
    seen = seen_of(incident)
    if seen in ("probe_failed", "budget_exhausted"):
        return [_signal("no_close_check", seen)]
    down = floor_seen(incident)
    out = []
    if first_look == "reported" and not down:
        out.append(_signal("disagreement", "reported_nobody_on_floor"))
    if first_look == "suspected" and down:
        out.append(_signal("disagreement", "suspected_someone_on_floor"))
    if not down:
        out.append(_signal("no_floor_seen", seen))
    sequence = incident.get("sequence", [])
    on = [s for s in sequence if s["posture"] in floor]
    if down:
        if len(on) < D["few_floor_frames"]["min_frames"]:
            out.append(_signal("few_floor_frames", len(on)))
        o = incident["outcome"]
        visible_not_floor = o["kind"] == "stood_up" or (o["kind"] == "last_seen" and o.get("posture") not in floor | {"not_visible"})
        if incident["floor_seconds"] < D["short_floor"]["min_s"] and visible_not_floor:
            out.append(_signal("short_floor", incident["floor_seconds"]))
        if not incident["arrival"]["observed"]:
            out.append(_signal("arrival_not_seen", incident["arrival"]["why"]))
        boxes = [s for s in on if "h" in s and "w" in s and "x" in s]
        if boxes and frame_size:
            W, H = frame_size
            height = median(s["h"] * H for s in boxes)
            if height < D["small_person"]["max_height_px"]:
                out.append(_signal("small_person", round(height)))
            gap = min(min((s["x"] - s["w"] / 2) * W, (s["y"] - s["h"] / 2) * H, (1 - s["x"] - s["w"] / 2) * W,
                          (1 - s["y"] - s["h"] / 2) * H) for s in boxes)
            if gap < D["image_edge"]["max_px"]:
                out.append(_signal("image_edge", max(0, round(gap))))
        if incident["max_displacement"] > D["moving_on_floor"]["max_displacement"]:
            out.append(_signal("moving_on_floor", incident["max_displacement"]))
    seat_times = [s["t_us"] for s in sequence
                  if s["posture"] == "sitting_on_seat" or (s["posture"] in floor and s.get("seat_nearby"))]
    if seat_times:
        out.append(_signal("seat_nearby", seat_times[0]))
    if down:
        state = [s["posture"] in floor for s in sequence if s["posture"] != "not_visible"]
        first = state.index(True)
        back = next((k for k in range(first + 1, len(state)) if not state[k]), None)
        if back is not None and any(state[back + 1:]):
            out.append(_signal("posture_flicker", " → ".join(dict.fromkeys(
                s["posture"] for s in sequence if s["posture"] != "not_visible"))))
        by_t = {f["t_us"]: f for f in incident.get("frames", [])}
        last = None
        for s in sequence:
            f = by_t.get(s["t_us"])
            if s["source"] == "followup" and f is not None and last is not None:
                near = sum(_distance((p["x"], p["y"]), last, aspect) <= D["identity_uncertain"]["max_distance"]
                           for p in f["persons"])
                if near >= 2:
                    out.append(_signal("identity_uncertain", s["t_us"]))
                    break
            if "x" in s:
                last = (s["x"], s["y"])
    return out


def mark(incident, *, first_look, frame_size=None, aspect, rules=RULES):
    """Add first_look, doubt_signals and status (look_closely / no_doubt_signal) to an incident, in place."""
    incident["first_look"] = first_look
    incident["doubt_signals"] = doubt_signals(incident, first_look=first_look, frame_size=frame_size, aspect=aspect, rules=rules)
    incident["status"] = LOOK_CLOSELY if incident["doubt_signals"] else NO_DOUBT_SIGNAL
    incident.pop("reason", None)
    return incident


def marked(incident, *, first_look, frame_size=None, aspect):
    """The incident as shown to the guard; incidents stored before rules v3 get their signals computed on read."""
    if "doubt_signals" in incident:
        return incident
    legacy = {k: v for k, v in incident.items() if k not in ("status", "reason")}
    legacy["seen"] = seen_of(incident)
    return mark(legacy, first_look=first_look, frame_size=frame_size, aspect=aspect)


def look_closely(incident):
    return incident.get("status") == LOOK_CLOSELY


def order(incidents):
    """Look closely first, then by time."""
    return sorted(incidents, key=lambda i: (not look_closely(i), i.get("first_floor_us", i["anchor_us"])))


# ---------- System's assessment: one sentence from the timed postures, an unverified opinion ----------

ASSESSMENT_PROMPT = (
    "Below are the postures measured for one person in a video, with times. Give one short sentence (at most 30 "
    "words) saying what these postures are consistent with. If you mention a fall, say only that the postures are "
    "consistent with a fall, together with any other reading they are also consistent with. Never state that "
    "something happened. Do not mention health, injury, intoxication, intent, identity, age or gender. Use only the "
    "facts below.\n\n{facts}"
)
_FALL_WORDS = re.compile(r"\b(fall\w*|fell|collaps\w*|trip\w*|slip\w*|stumbl\w*)\b", re.I)
_HEDGE = re.compile(r"\b(consistent with|compatible with|could|may|might|possibl\w*)\b", re.I)
_FORBIDDEN = re.compile(
    r"\b(injur\w*|hurt|wound\w*|blood\w*|unconscious\w*|faint\w*|passed out|unwell|ill|sick\w*|medical|emergenc\w*|"
    r"seizure\w*|stroke|heart|pain\w*|drunk\w*|intoxicat\w*|overdos\w*|deliberate\w*|intentional\w*|on purpose|"
    r"pretend\w*|fak\w*|attack\w*|assault\w*|push\w*|fight\w*|suspicious|victim\w*|man|men|woman|women|boy|girl|"
    r"elderly|old|young|homeless|he|she|his|her|him|hers)\b", re.I)
MAX_ASSESSMENT_CHARS = 240


def assessment_facts(incident):
    """The only input of the assessment: timed postures of the checked person and the measured facts.
    Never the first look's description, never the doubt signals."""
    segments = seen_segments(incident.get("sequence", []))
    lines = [f"- {_POSTURE['en'][p]} from {clock(a)} to {clock(b)}" for p, a, b in segments]
    facts = facts_lines(incident, "en") if floor_seen(incident) else []
    return ("Postures of the person checked:\n" + "\n".join(lines)
            + ("\nMeasured facts:\n" + "\n".join(f"- {f}" for f in facts) if facts else ""))


def assessment_prompt(incident):
    return ASSESSMENT_PROMPT.format(facts=assessment_facts(incident))


def check_assessment(text):
    """None when the sentence may be shown, otherwise why it is rejected."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    text = text.strip()
    if len(text) > MAX_ASSESSMENT_CHARS:
        return "too_long"
    if "\n" in text or re.search(r"[.!?](?=\s)", text.rstrip(".!? ")):
        return "more_than_one_sentence"
    if _FORBIDDEN.search(text):
        return "forbidden_word"
    if _FALL_WORDS.search(text) and not _HEDGE.search(text):
        return "fall_stated_as_fact"
    return None


def assess(incident, ask_assessment):
    """Ask for the System's assessment of one incident; the result never changes the status or the order."""
    if not incident.get("sequence"):
        return {"status": "not_requested", "text": None}
    try:
        text, metadata = ask_assessment(assessment_prompt(incident))
    except Exception as exc:  # noqa: BLE001 - no assessment is shown, the card is unchanged
        return {"status": "failed", "text": None, "error": str(exc), "inference": getattr(exc, "metadata", None)}
    problem = check_assessment(text)
    if problem:
        return {"status": "rejected", "text": None, "rejected_text": text, "why": problem, "inference": metadata}
    return {"status": "ok", "text": text.strip(), "inference": metadata}


def assessment_text(incident):
    a = incident.get("assessment") or {}
    return a.get("text") if a.get("status") == "ok" else None


# ---------- plain-language facts (no interpretation words) ----------

_POSTURE = {
    "fr": {"standing": "debout", "bending": "penchée", "kneeling": "à genoux", "sitting_on_seat": "assise sur un siège",
           "sitting_on_floor": "assise au sol", "lying_on_floor": "allongée au sol", "not_visible": "hors de vue"},
    "en": {"standing": "standing", "bending": "bending", "kneeling": "kneeling", "sitting_on_seat": "sitting on a seat",
           "sitting_on_floor": "sitting on the floor", "lying_on_floor": "lying on the floor", "not_visible": "out of view"},
}
_SEEN = {
    "fr": {
        "seated": "l'inspection fine montre une personne assise sur un siège, personne au sol",
        "kneeling": "l'inspection fine montre une personne à genoux, personne au sol",
        "no_floor": "l'inspection fine ne montre personne au sol",
        "upright_throughout": "l'inspection fine montre les personnes debout tout du long",
        "no_person": "l'inspection fine ne montre personne",
        "probe_failed": "l'inspection fine a échoué",
        "budget_exhausted": "pas d'inspection fine (budget de la vidéo épuisé)",
    },
    "en": {
        "seated": "the close check shows a person sitting on a seat, nobody on the floor",
        "kneeling": "the close check shows a person kneeling, nobody on the floor",
        "no_floor": "the close check shows nobody on the floor",
        "upright_throughout": "the close check shows the people standing throughout",
        "no_person": "the close check shows nobody",
        "probe_failed": "the close check failed",
        "budget_exhausted": "no close check (the video's check budget was used up)",
    },
}


def clock(us):
    minutes, rest = divmod(max(0, us), 60 * US)
    return f"{minutes:02d}:{rest / US:05.2f}"


def seen_segments(sequence):
    """Consecutive postures of the checked person: [(posture, first_us, last_us)]."""
    out = []
    for s in sequence:
        if out and out[-1][0] == s["posture"]:
            out[-1] = (s["posture"], out[-1][1], s["t_us"])
        else:
            out.append((s["posture"], s["t_us"], s["t_us"]))
    return out


def probe_seen(incident, lang="fr"):
    """What the close check saw for the checked person, as posture segments with times."""
    P, fr = _POSTURE[lang], lang == "fr"
    segments = seen_segments(incident.get("sequence", []))
    if not segments:
        return None
    parts = [f"{P[p]} {clock(a)}" + (f"–{clock(b)}" if b != a else "") for p, a, b in segments]
    head = "Ce que l'inspection fine a vu" if fr else "What the close check saw"
    return f"{head} : " + " ; ".join(parts) + "." if fr else f"{head}: " + "; ".join(parts) + "."


def key_times(incident, limit=4):
    """Times of the images to show the guard (before, on the floor, until, after; or what was seen)."""
    if floor_seen(incident):
        times = [incident.get("arrival", {}).get("upright_us"), incident["first_floor_us"],
                 incident.get("floor_until_us"), incident.get("outcome", {}).get("at_us")]
    else:
        segments = seen_segments(incident.get("sequence", []))
        times = [a for p, a, _ in segments if p not in ("standing", "not_visible")] or [s[1] for s in segments]
        times = [segments[0][1], *times, segments[-1][2]] if segments else []
    return list(dict.fromkeys(t for t in times if t is not None))[:limit]


def facts_lines(incident, lang="fr"):
    """Plain-language lines: only measured facts, no interpretation."""
    P, fr = _POSTURE[lang], lang == "fr"
    if not floor_seen(incident):
        seen = seen_of(incident)
        why = _SEEN[lang].get(seen, seen)
        lines = [(f"Signalé au sol par l'analyse vidéo vers {clock(incident['anchor_us'])} ; {why}." if fr
                  else f"Reported on the floor by the video analysis at about {clock(incident['anchor_us'])}; {why}.")]
        shown = probe_seen(incident, lang)
        return lines + ([shown] if shown else [])
    posture = P[incident["floor_postures"][0]["posture"]]
    lines = [f"Une personne est {posture} à partir de {clock(incident['first_floor_us'])}." if fr
             else f"A person is {posture} from {clock(incident['first_floor_us'])}."]
    for seg in incident["floor_postures"][1:]:
        lines.append(f"Puis {P[seg['posture']]} à {clock(seg['from_us'])}." if fr
                     else f"Then {P[seg['posture']]} at {clock(seg['from_us'])}.")
    a = incident["arrival"]
    if a["observed"]:
        via = (", en passant par " + ", ".join(P[v] for v in a["via"]) if fr else ", via " + ", ".join(P[v] for v in a["via"])) if a["via"] else ""
        lines.append(f"De debout ({clock(a['upright_us'])}) à au sol en {a['seconds']:.1f} s{via}." if fr
                     else f"From standing ({clock(a['upright_us'])}) to the floor in {a['seconds']:.1f} s{via}.")
    else:
        before = ", ".join(P[v] for v in a.get("earlier_postures", []))
        if a["why"] == "already_on_floor":
            lines.append("Arrivée au sol non observée : déjà au sol au début de l'observation." if fr
                         else "Reaching the floor was not seen: already on the floor when observation began.")
        else:
            lines.append(f"Arrivée au sol non observée (avant : {before} ; pas vue debout)." if fr
                         else f"Reaching the floor was not seen (before: {before}; not seen standing).")
    o, seconds = incident["outcome"], incident["floor_seconds"]
    if o["kind"] == "stood_up":
        via = (" après " + ", ".join(P[v] for v in o["via"]) if fr else " after " + ", ".join(P[v] for v in o["via"])) if o["via"] else ""
        lines.append(f"Vue au sol jusqu'à {clock(incident['floor_until_us'])} ({seconds:.1f} s) ; debout à {clock(o['at_us'])}{via}." if fr
                     else f"Seen on the floor until {clock(incident['floor_until_us'])} ({seconds:.1f} s); standing at {clock(o['at_us'])}{via}.")
    elif o["kind"] == "on_floor_at_end":
        lines.append(f"Toujours au sol à la fin de la vidéo ({clock(o['at_us'])}), au moins {seconds:.1f} s." if fr
                     else f"Still on the floor at the end of the video ({clock(o['at_us'])}), at least {seconds:.1f} s.")
    elif o["kind"] == "last_seen":
        lines.append(f"Vue au sol jusqu'à {clock(incident['floor_until_us'])} ({seconds:.1f} s) ; à {clock(o['at_us'])} : {P[o['posture']]}." if fr
                     else f"Seen on the floor until {clock(incident['floor_until_us'])} ({seconds:.1f} s); at {clock(o['at_us'])}: {P[o['posture']]}.")
    else:
        lines.append(f"Toujours au sol à {clock(o['at_us'])}, au moins {seconds:.1f} s (suivi arrêté)." if fr
                     else f"Still on the floor at {clock(o['at_us'])}, at least {seconds:.1f} s (follow-up stopped).")
    if seen_of(incident) == "on_floor_not_near_report":
        lines.append(f"Signalé vers {clock(incident['anchor_us'])} ; la première image au sol est à {clock(incident['first_floor_us'])}." if fr
                     else f"Reported at about {clock(incident['anchor_us'])}; the first image on the floor is at {clock(incident['first_floor_us'])}.")
    return lines


def signal_text(signal, lang="en"):
    """One doubt signal with its measured value, in plain language."""
    code, v, fr = signal["code"], signal.get("value"), lang == "fr"
    number, at = isinstance(v, (int, float)), isinstance(v, int)
    if code == "disagreement":
        if v == "reported_nobody_on_floor":
            return ("Désaccord : le premier regard la dit au sol, l'inspection fine ne voit personne au sol" if fr
                    else "Disagreement: the first look reported someone on the floor; the close check shows nobody on the floor")
        return ("Désaccord : le premier regard avait seulement un doute, l'inspection fine voit quelqu'un au sol" if fr
                else "Disagreement: the first look only suspected it; the close check shows someone on the floor")
    texts = {
        "no_floor_seen": ("L'inspection fine ne voit personne au sol", "The close check shows nobody on the floor"),
        "few_floor_frames": (f"Seulement {v} image(s) au sol dans l'inspection fine", f"Only {v} close-check image(s) on the floor"),
        "short_floor": (f"Au sol {v:.1f} s seulement, puis vue hors du sol" if number else "Au sol peu de temps",
                        f"On the floor only {v:.1f} s, then seen off the floor" if number else "On the floor briefly"),
        "arrival_not_seen": ("Arrivée au sol non observée", "Reaching the floor was not seen"),
        "small_person": (f"Personne petite dans l'image ({v} px de haut)", f"Small in the image ({v} px tall)"),
        "image_edge": (f"Au bord de l'image ({v} px du bord)", f"At the image edge ({v} px from the border)"),
        "moving_on_floor": (f"Se déplace de {v:.0%} de la largeur de l'image alors qu'elle est dite au sol" if number else "Se déplace au sol",
                            f"Moves {v:.0%} of the image width while reported on the floor" if number else "Moves while on the floor"),
        "seat_nearby": (f"Siège à côté de la personne (vu à {clock(v)})" if at else "Siège à côté de la personne",
                        f"A seat next to the person (seen at {clock(v)})" if at else "A seat next to the person"),
        "posture_flicker": (f"Posture changeante : {v}", f"Changing posture: {v}"),
        "identity_uncertain": (f"Plusieurs personnes près de sa dernière position à {clock(v)} : identité incertaine dans le suivi" if at
                               else "Identité incertaine dans le suivi",
                               f"Several people near the last known position at {clock(v)}: identity uncertain in the follow-up" if at
                               else "Identity uncertain in the follow-up"),
        "no_close_check": ("Pas d'inspection fine (" + _SEEN["fr"].get(v, str(v)) + ")",
                           "No close check (" + _SEEN["en"].get(v, str(v)) + ")"),
    }
    fr_text, en_text = texts.get(code, (code, code))
    return fr_text if fr else en_text


def alerting(incidents):
    """Every incident goes to the guard (watch-list level 1), never dismissed."""
    return list(incidents)


def render_markdown(incidents):
    shown = order(alerting(incidents))
    closely = sum(look_closely(i) for i in shown)
    lines = [f"## Personnes au sol, pour le garde ({len(shown)}" + (f", dont {closely} à regarder de près)" if closely else ")"), ""]
    if not shown:
        lines += ["Aucune personne au sol signalée.", ""]
    else:
        lines += ["Faits mesurés par une inspection fine (environ 4 images par seconde) et un suivi (1 image par seconde). "
                  "Le système ne décide pas : il signale ce qui peut faire douter. Le garde juge.", ""]
    for n, incident in enumerate(shown, 1):
        badge = "à regarder de près" if look_closely(incident) else "aucun signal de doute mesuré"
        lines.append(f"{n}. **Personne au sol — {badge}**")
        lines += [f"   - {line}" for line in facts_lines(incident, "fr")]
        text = assessment_text(incident)
        lines.append(f"   - Avis du système (non vérifié, en anglais) : {text}" if text else "   - Avis du système : aucun.")
        signals = incident.get("doubt_signals", [])
        lines.append("   - Signaux de doute : " + ("; ".join(signal_text(s, "fr") for s in signals) + "." if signals
                                                  else "aucun signal mesuré (cela ne veut pas dire que c'est vrai)."))
        lines.append("")
    return "\n".join(lines) + "\n"
