"""person_on_floor: measured facts about a person sitting or lying on the floor (rules in floor_rules.json).

The system describes, it does not interpret: no "fall", no "sudden" or "gradual". For each person_on_floor
candidate seen by Perception, the code asks Perception a neutral posture question on a dense frame sample
(the probe), follows the person while they stay on the floor (follow-ups), and computes the facts itself:
how the person reached the floor (measured seconds and intermediate postures), posture on the floor, time on
the floor, and what came next (stood up at, still on the floor at the end, or last seen). "Facts verified"
means those facts were checked by the probe and the rules; it never means "a fall happened".

The model call is injected (`ask(times_us, phase)`); everything else here is deterministic.
"""
from __future__ import annotations

import json
from math import hypot
from pathlib import Path

RULES = json.loads(Path(__file__).with_name("floor_rules.json").read_text())
FLOOR_CATEGORY = "person_on_floor"
LEGACY_CATEGORIES = ("person_fell",)  # archived runs: same candidate, older wording
# Only the current category starts a check; archived person_fell observations are read as they were recorded.
CANDIDATE_CATEGORIES = (FLOOR_CATEGORY,)
US = 1_000_000

PROMPT = (
    "For each image, list every person you can see. For each person give: id, a label P1, P2, ... that stays "
    "the same for the same person in all images; posture, exactly one of: {vocabulary}; x and y, the approximate "
    "centre of the person as fractions of the image width and height, from 0 to 1. Use sitting_on_seat for a person "
    "sitting on a chair, bench or other seat, and sitting_on_floor only when the person sits directly on the floor. "
    "Report only what is visible in each image. Return an empty list for an image with nobody visible."
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


def anchor_us(finding):
    frames = finding.citation.frames
    return min(f.source_time_us for f in frames) if frames else finding.citation.interval.start_us


# ---------- facts from one person's sequence ----------

def _distance(a, b, aspect):
    return hypot(a[0] - b[0], (a[1] - b[1]) * aspect)


def describe(seq, anchor, *, aspect, video_end_us, followup_stopped=False, rules=RULES):
    """Facts for one person's sequence [(t_us, posture, x, y, source)], source 'probe' or 'followup'.

    Returns a dict with status 'verified', 'to_review' or 'kneeling_only', a reason when not verified,
    and the measured facts. Times are integer microseconds.
    """
    upright, floor = set(rules["upright"]), set(rules["on_floor"])
    labels = [s[1] for s in seq]
    visible = [l for l in labels if l != "not_visible"]
    base = {"sequence": [{"t_us": t, "posture": p, "source": src} for t, p, _, _, src in seq]}
    if not any(l in floor for l in labels):
        if "kneeling" in visible:
            return {**base, "status": "kneeling_only", "reason": "kneeling_only"}
        if not visible:
            reason = "no_person"
        elif all(l in upright for l in visible):
            reason = "upright_throughout"
        elif "sitting_on_seat" in visible:
            reason = "seated"
        else:
            reason = "no_floor"
        return {**base, "status": "to_review", "reason": reason}
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
    facts = {**base, "first_floor_us": first_us, "floor_until_us": until_us,
             "floor_seconds": round((until_us - first_us) / US, 2), "floor_postures": segments,
             "arrival": arrival, "outcome": outcome, "max_displacement": round(moved, 4),
             "followup_still_on_floor": corroborated}
    lo, hi = rules["near_candidate_s"]
    if not lo * US <= first_us - anchor <= hi * US:
        return {**facts, "status": "to_review", "reason": "not_near_candidate"}
    if until_us - first_us < rules["min_floor_s"] * US:
        return {**facts, "status": "to_review", "reason": "floor_too_short"}
    if moved > rules["max_floor_displacement"]:
        return {**facts, "status": "to_review", "reason": "moving_on_floor"}
    if not (arrival["observed"] or corroborated):
        return {**facts, "status": "to_review", "reason": "not_corroborated"}
    return {**facts, "status": "verified", "reason": None}


_RANK = ["verified", "moving_on_floor", "floor_too_short", "not_corroborated", "not_near_candidate",
         "kneeling_only", "seated", "no_floor", "upright_throughout", "no_person"]


def _rank(facts):
    return _RANK.index(facts["reason"] or "verified")


# ---------- orchestration: probe, follow-ups, merging, budget ----------

def _tracks(frames):
    """{id: [(t_us, posture, x, y)]} from one call's frames, missing persons as not_visible."""
    ids = list(dict.fromkeys(p["id"] for f in frames for p in f["persons"]))
    out = {pid: [] for pid in ids}
    for f in frames:
        seen = {p["id"]: p for p in f["persons"]}
        for pid in ids:
            p = seen.get(pid)
            out[pid].append((f["t_us"], p["posture"], p["x"], p["y"]) if p else (f["t_us"], "not_visible", None, None))
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
            out.append((f["t_us"], p["posture"], p["x"], p["y"], "followup"))
            last_xy = (p["x"], p["y"])
        else:
            out.append((f["t_us"], "not_visible", None, None, "followup"))
    return out


def _still_on_floor(seq, rules):
    tail = [s for s in seq if s[1] != "not_visible"]
    return bool(tail) and tail[-1][1] in rules["on_floor"]


def check(candidates, ask, *, duration_us, aspect, rules=RULES):
    """Incidents for person_on_floor candidates.

    candidates: [(observation_id, anchor_us)]. ask(times_us, phase) -> (inspection_id, frames) where frames is
    [{"t_us", "display_index", "frame_id", "persons": [{"id", "posture", "x", "y"}]}], or raises an exception
    carrying the failure text. Returns a list of incident dicts.
    """
    incidents, used = [], 0
    gap = round(rules["merge_gap_s"] * US)
    for observation_id, anchor in sorted(candidates, key=lambda c: (c[1], c[0])):
        home = next((i for i in incidents if i["span_us"][0] - gap <= anchor <= i["span_us"][1] + gap), None)
        if home is not None:
            home["observation_ids"].append(observation_id)
            continue
        incident = {"observation_ids": [observation_id], "anchor_us": anchor, "inspections": [], "frames": []}
        incidents.append(incident)
        if used >= rules["max_inspections_per_video"]:
            incident.update(status="to_review", reason="budget_exhausted", span_us=[anchor, anchor])
            continue
        times = probe_times(anchor, duration_us, rules)
        used += 1
        try:
            inspection_id, frames = ask(times, "floor_probe")
        except Exception as exc:  # noqa: BLE001 - a failed probe leaves the alert to review, never dismissed
            incident.update(status="to_review", reason="probe_failed", error=str(exc), span_us=[anchor, anchor])
            continue
        incident["inspections"].append(inspection_id)
        incident["frames"].extend(frames)
        people = []
        for pid, track in _tracks(frames).items():
            seq = [(*s, "probe") for s in track]
            people.append((pid, seq, describe(seq, anchor, aspect=aspect, video_end_us=duration_us, rules=rules)))
        if not people:
            incident.update(status="to_review", reason="no_person", span_us=[anchor, times[-1] if times else anchor],
                            sequence=[])
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
        incident["span_us"] = [facts.get("first_floor_us", anchor), seq[-1][0]]
    return incidents


# ---------- plain-language facts (no interpretation words) ----------

_POSTURE = {
    "fr": {"standing": "debout", "bending": "penchée", "kneeling": "à genoux", "sitting_on_seat": "assise sur un siège",
           "sitting_on_floor": "assise au sol", "lying_on_floor": "allongée au sol", "not_visible": "hors de vue"},
    "en": {"standing": "standing", "bending": "bending", "kneeling": "kneeling", "sitting_on_seat": "sitting on a seat",
           "sitting_on_floor": "sitting on the floor", "lying_on_floor": "lying on the floor", "not_visible": "out of view"},
}
_REASON = {
    "fr": {
        "moving_on_floor": "la personne se déplace pendant qu'elle semble au sol",
        "floor_too_short": "au sol moins de 2 s dans l'inspection fine",
        "not_corroborated": "arrivée au sol non observée et pas de suivi la montrant encore au sol",
        "not_near_candidate": "l'inspection fine ne montre personne au sol à ce moment-là",
        "seated": "l'inspection fine montre une personne assise sur un siège, personne au sol",
        "no_floor": "l'inspection fine ne montre personne au sol",
        "upright_throughout": "l'inspection fine montre les personnes debout tout du long",
        "no_person": "l'inspection fine ne montre personne",
        "probe_failed": "l'inspection fine a échoué",
        "budget_exhausted": "pas d'inspection fine (budget de la vidéo épuisé)",
    },
    "en": {
        "moving_on_floor": "the person moves while apparently on the floor",
        "floor_too_short": "on the floor for less than 2 s in the close check",
        "not_corroborated": "reaching the floor was not seen and no follow-up shows the person still on the floor",
        "not_near_candidate": "the close check shows nobody on the floor at that moment",
        "seated": "the close check shows a person sitting on a seat, nobody on the floor",
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


def facts_lines(incident, lang="fr"):
    """Plain-language lines: only measured facts, no interpretation."""
    P, fr = _POSTURE[lang], lang == "fr"
    if incident.get("first_floor_us") is None:
        why = _REASON[lang].get(incident["reason"], incident["reason"])
        if incident["status"] == "kneeling_only":
            seen = [s for s in incident.get("sequence", []) if s["posture"] == "kneeling"]
            span = f"{clock(seen[0]['t_us'])}–{clock(seen[-1]['t_us'])}" if seen else ""
            return [f"Une personne à genoux {span}, pas au sol." if fr else f"A person kneeling {span}, not on the floor."]
        return [(f"Signalé par l'analyse vidéo vers {clock(incident['anchor_us'])} ; {why}." if fr
                 else f"Reported by the video analysis at about {clock(incident['anchor_us'])}; {why}.")]
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
    if incident["status"] != "verified":
        why = _REASON[lang].get(incident["reason"], incident["reason"])
        lines.append(f"Faits non vérifiés : {why}." if fr else f"Facts not verified: {why}.")
    return lines


def alerting(incidents):
    """Every incident except kneeling-only becomes an alert for the guard."""
    return [i for i in incidents if i["status"] != "kneeling_only"]


def render_markdown(incidents):
    shown = alerting(incidents)
    lines = [f"## Personnes au sol ({len(shown)})", ""]
    if not shown:
        lines += ["Aucune personne au sol signalée.", ""]
    else:
        lines += ["Faits mesurés par une inspection fine (environ 4 images par seconde) et un suivi (1 image par seconde). "
                  "« Faits vérifiés » veut dire que ces faits ont été contrôlés, pas que l'on sait ce qui s'est passé : "
                  "le garde juge.", ""]
    for n, incident in enumerate(shown, 1):
        status = "faits vérifiés" if incident["status"] == "verified" else "à vérifier"
        lines.append(f"{n}. **Personne au sol — {status}**")
        lines += [f"   - {line}" for line in facts_lines(incident, "fr")]
        lines.append("")
    notes = [i for i in incidents if i["status"] == "kneeling_only"]
    if notes:
        lines += ["### Chronologie (sans alerte)", ""] + [f"- {facts_lines(i, 'fr')[0]}" for i in notes] + [""]
    return "\n".join(lines) + "\n"
