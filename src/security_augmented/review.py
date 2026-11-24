"""Operator review queue for unconfirmed security observations.

Source rule: group plan "Security, Augmented: project concept and work plan", p. 8, Guardrails:
"Missing context produces unknown and a question to the operator" and "Person-down and fire events
are never dismissed by the agent". See docs/operator-review.md.

The strict ``supported`` verdict is unchanged. A ``needs_review`` alert is never evidence: retrieval,
event anchors and the report lead keep using supported events only.
"""
import re

from .video import _id
from .workflow import PRIORITY_LABELS, _time

# Entry into an area needs a configured monitored zone (plan detector C1); none exists yet.
ZONE_CATEGORIES = frozenset({"person_enters_area"})
# Never dismissed by the agent, even when verification contradicts the observation.
NEVER_DISMISSED = frozenset({"person_fell"})
MAX_REVIEW_FRAMES = 6

_WHAT = {
    "object_placed": "Objet déposé", "object_removed": "Objet retiré", "person_fell": "Personne à terre",
    "person_enters_area": "Entrée dans une zone", "object_appeared": "Objet apparu",
    "object_disappeared": "Objet disparu",
}
_QUESTION = {
    "object_placed": "Un objet est-il posé puis laissé sur place ?",
    "object_removed": "Un objet est-il retiré ?",
    "person_fell": "Une personne est-elle à terre ?",
    "person_enters_area": "Une personne entre-t-elle dans la zone surveillée ?",
    "object_appeared": "Un objet apparaît-il vraiment, sans être déjà présent avant ?",
    "object_disappeared": "Un objet disparaît-il vraiment ?",
}
_WHY = {
    "not_checked": "Non vérifié : laissé de côté au tri, faute de place de vérification.",
    "missing_corroboration": "Vérifié mais non confirmé : les images examinées ne suffisent pas à le corroborer.",
    "inspection_rejected": "La vérification n'a pas pu obtenir de nouvelles images.",
    "inspection_rejected/no_new_frames": ("La vérification n'a pas pu obtenir de nouvelles images : "
                                          "celles demandées avaient déjà toutes été examinées."),
    "invalid_verdict": "La décision de vérification était invalide et a été refusée.",
    "unfinished": "La vérification s'est arrêtée avant de conclure (limite d'itérations, d'appels ou échec d'outil).",
    "contradicted": ("La vérification juge que les images ne le montrent pas. "
                     "À confirmer quand même : ce type d'événement n'est jamais écarté par l'agent."),
}
_UNFINISHED = frozenset({
    "Verification iteration limit reached.", "Verification ended without a valid supported verdict.",
    "Verification ended without an accepted verdict.", "Source inspection failed.",
})
_AFFIRMATIVE = re.compile(r"\b(establish(es|ed)?|confirm(s|ed)?|clearly (shows|documents)|is supported)\b", re.I)
_NEGATION = re.compile(r"\b(not|cannot|no|insufficient|unclear|without)\b", re.I)
_FRAME_LABEL = re.compile(r"\bF(\d+)(?:\s*(?:-|–|to|through)\s*F?(\d+))?")


def reason_code(event, trace):
    """Deterministic reason an unconfirmed event is not supported, derived from the run trace."""
    if event.verdict == "unsupported":
        return "contradicted"
    reason = event.reason
    if reason.endswith("during triage."):
        return "not_checked"
    if reason == "Invalid verdict or citation.":
        return "invalid_verdict"
    if reason == "Recovery yielded no additional cited evidence.":
        return "missing_corroboration"
    if reason in _UNFINISHED:
        return "unfinished"
    seed = event.observation_ids[0]
    for decision in reversed(trace):
        details = decision.details or {}
        if decision.actor != "verification" or (
                seed not in decision.observation_ids and details.get("candidate_id") != seed):
            continue
        if decision.reason == reason and decision.action == "inspection_rejected":
            return f"inspection_rejected/{details['code']}" if details.get("code") else "inspection_rejected"
        if decision.reason == reason and decision.action == "evidence_insufficient":
            return "missing_corroboration"
    # The verifier itself returned insufficient with its own explanation.
    if any(d.actor == "verification" and d.action == "decision" and reason and reason[:80] in d.reason for d in trace):
        return "missing_corroboration"
    return "unfinished"


def _frames(event, description, inspections):
    cited = list({f.id: f for c in event.citations for f in c.frames}.values())
    cited.sort(key=lambda f: (f.source_time_us, f.display_index))
    inspection = inspections.get(event.citations[0].inspection_id) if event.citations else None
    by_label = {f"F{i}": frame for i, frame in enumerate(inspection.frames, 1)} if inspection else {}
    label_of = {frame.id: label for label, frame in by_label.items()}
    named = []
    for match in _FRAME_LABEL.finditer(description or ""):
        for number in match.groups():
            if number and (frame := by_label.get(f"F{number}")) is not None:
                named.append(frame)
    chosen = {f.id: f for f in (cited[:1] + cited[-1:] + named)}
    picked = sorted(chosen.values(), key=lambda f: (f.source_time_us, f.display_index))
    if len(picked) > MAX_REVIEW_FRAMES:  # keep first and last, then the earliest named frames
        middle = [f for f in picked if f.id not in (cited[0].id, cited[-1].id)][:MAX_REVIEW_FRAMES - 2]
        picked = sorted([cited[0], *middle, cited[-1]], key=lambda f: (f.source_time_us, f.display_index))
    return [{"id": f.id, "display_index": f.display_index, "source_time_us": f.source_time_us,
             "label": label_of.get(f.id)} for f in picked], len(cited)


def review(events, trace, evidence):
    """Split unconfirmed security events into operator alerts and recorded non-alerts."""
    descriptions = {f.observation.id: f.observation.description for entry in evidence for f in entry.findings}
    inspections = {entry.inspection.id: entry.inspection for entry in evidence if entry.inspection is not None}
    alerts, not_alerted = [], []
    for event in sorted(events, key=lambda e: (e.interval.start_us, e.category)):
        if event.category not in PRIORITY_LABELS or event.verdict == "supported":
            continue
        seed = event.observation_ids[0]
        code = reason_code(event, trace)
        base = {"category": event.category, "observation_id": seed,
                "interval": {"start_us": event.interval.start_us, "end_us": event.interval.end_us},
                "reason_code": code, "model_reason": event.reason}
        if event.category in ZONE_CATEGORIES:
            not_alerted.append({**base, "why": "zone_undefined"})
            continue
        if code == "contradicted" and event.category not in NEVER_DISMISSED:
            not_alerted.append({**base, "why": "contradicted"})
            continue
        description = descriptions.get(seed, "")
        frames, cited = _frames(event, description, inspections)
        alerts.append({
            "id": _id("alert", event.citations[0].video_id if event.citations else None, seed, event.category),
            "status": "needs_review", **base, "frames": frames, "cited_frame_count": cited,
            "description": description,
            "model_reason_affirmative": bool(_AFFIRMATIVE.search(event.reason) and not _NEGATION.search(event.reason)),
            "question": _QUESTION[event.category], "operator_label": None,
        })
    supported = sum(1 for e in events if e.category in PRIORITY_LABELS and e.verdict == "supported")
    return {
        "alerts": alerts, "not_alerted": not_alerted,
        "counts": {"needs_review": len(alerts), "supported_security": supported,
                   "not_alerted": {why: sum(1 for n in not_alerted if n["why"] == why)
                                   for why in ("zone_undefined", "contradicted")}},
    }


def _span(interval):
    return f"{_time(interval['start_us'])}–{_time(interval['end_us'] - 1)}"


def render(result):
    """Plain-language operator section placed before the confirmed findings."""
    alerts = result["alerts"]
    lines = [f"## Alertes à vérifier ({len(alerts)})", ""]
    if not alerts:
        lines += ["Aucune alerte de sécurité non confirmée.", ""]
    else:
        lines += ["Observations de sécurité non confirmées par la vérification automatique. "
                  "Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.", ""]
    for number, alert in enumerate(alerts, 1):
        why = _WHY.get(alert["reason_code"], _WHY.get(alert["reason_code"].split("/")[0], alert["reason_code"]))
        model = f" Raison enregistrée : « {alert['model_reason']} »"
        if alert["model_reason_affirmative"]:
            model += " (ce texte du modèle paraît affirmatif malgré le verdict non confirmé)"
        views = ", ".join(f"{f['label'] + ' ' if f['label'] else ''}{_time(f['source_time_us'])} (frame {f['display_index']})"
                          for f in alert["frames"])
        lines += [
            f"{number}. **{_WHAT[alert['category']]}** — {_span(alert['interval'])}",
            f"   - Pourquoi ce n'est pas confirmé : {why}{model}",
            f"   - Images à regarder : {views} ({len(alert['frames'])} sur {alert['cited_frame_count']} images citées)",
            *([f"   - Description de la perception : « {alert['description']} »"] if alert["description"] else []),
            f"   - Question : {alert['question']}", "",
        ]
    if result["not_alerted"]:
        lines += ["### Non retenus comme alertes", ""]
        for item in result["not_alerted"]:
            if item["why"] == "zone_undefined":
                text = ("aucune zone surveillée n'est configurée, l'entrée dans une zone ne peut pas être vérifiée "
                        "(ces alertes reviendront avec la configuration des zones).")
            else:
                text = f"écarté par la vérification, les images le contredisent. Raison : « {item['model_reason']} »"
            lines.append(f"- {_WHAT[item['category']]}, {_span(item['interval'])} : {text}")
        lines.append("")
    return "\n".join(lines) + "\n"
