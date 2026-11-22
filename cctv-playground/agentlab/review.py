"""The review step (task D3): a person decides on each alert, and every decision is logged.

The audit log is the record. The kit's decisions.jsonl is written as well, in the kit's own words,
so app.py and AlertStore.open_alerts read a decision correctly.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from agentlab import audit
from agentlab.actions import proposed_action
from fakecctv.alerts import AlertStore

REVIEWER = "Guard on duty"
FOR_ESCALATED = ("approve", "dismiss")
FOR_CLOSED = ("confirm", "reopen")
NEEDS_REASON = ("dismiss", "reopen")
OVERRIDES = ("dismiss", "reopen")
KIT_WORDS = {"approve": "approved", "dismiss": "dismissed by guard", "confirm": "confirmed", "reopen": "reopened"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
COLOURS = {"high": "31", "medium": "33", "low": "2"}  # red, yellow, dim


def find_alert(alerts: list[dict], ref: str) -> dict:
    for alert in alerts:
        if ref in (alert["id"], alert["candidate"]["candidate_id"]):
            return alert
    raise ValueError(f"No alert {ref} in this run.")


def decisions(run_dir: Path) -> dict[str, dict]:
    """The decision entry of each decided alert, by alert id."""
    return {e["alert_id"]: e for e in audit.read(run_dir) if e["type"] == "decision"}


def _undecided(run_dir: Path) -> list[dict]:
    done = decisions(run_dir)
    return [a for a in AlertStore(run_dir).all() if a["id"] not in done]


def pending(run_dir: Path) -> list[dict]:
    waiting = [a for a in _undecided(run_dir) if a["verdict"] == "escalate"]
    return sorted(waiting, key=lambda a: (PRIORITY_ORDER.get(a["priority"], len(PRIORITY_ORDER)), a["created"]))


def closed(run_dir: Path) -> list[dict]:
    return sorted((a for a in _undecided(run_dir) if a["verdict"] != "escalate"), key=lambda a: a["created"])


def decide(run_dir: Path, ref: str, decision: str, reason: str = "", reviewer: str = REVIEWER) -> dict:
    """Log a person's decision (and, for an approval, the action) and return the decision entry."""
    store = AlertStore(run_dir)
    alert = find_alert(store.all(), ref)
    alert_id, cand, verdict = alert["id"], alert["candidate"], alert["verdict"]

    earlier = decisions(run_dir).get(alert_id)
    if earlier:
        raise ValueError(f"{alert_id} was already decided ({earlier['decision']}).")
    allowed = FOR_ESCALATED if verdict == "escalate" else FOR_CLOSED
    if decision not in allowed:
        raise ValueError(f"Cannot {decision} {alert_id}: the agent's verdict was {verdict}. "
                         f"Use {' or '.join(allowed)}.")
    reason = reason.strip()
    if decision in NEEDS_REASON and not reason:
        raise ValueError("A reason is required to dismiss or reopen.")

    reviewer = reviewer.strip() or REVIEWER
    # The order matters: an action can never be in the log before its approval.
    entry = audit.append(run_dir, {
        "type": "decision", "alert_id": alert_id, "candidate_id": cand["candidate_id"], "decision": decision,
        "reason": reason, "reviewer": reviewer, "alert_site_time": alert["created"], "agent_verdict": verdict,
        "agreed": decision not in OVERRIDES})
    if decision == "approve":
        audit.append(run_dir, {
            "type": "action", "alert_id": alert_id, "action": proposed_action(cand["kind"], cand["zone"]),
            "approved_by": reviewer, "simulated": True})
    store.decide(alert_id, KIT_WORDS[decision], site_time=datetime.fromisoformat(alert["created"]), note=reason)
    return entry


def summary(run_dir: Path) -> dict:
    alerts = AlertStore(run_dir).all()
    entries = audit.read(run_dir)
    made = [e["decision"] for e in entries if e["type"] == "decision"]
    escalated = sum(1 for a in alerts if a["verdict"] == "escalate")
    overrides = sum(1 for d in made if d in OVERRIDES)
    return {
        "alerts": len(alerts), "escalated": escalated, "closed_by_agent": len(alerts) - escalated,
        "decisions": len(made),
        "approved": made.count("approve"), "dismissed": made.count("dismiss"),
        "confirmed": made.count("confirm"), "reopened": made.count("reopen"),
        "overrides": overrides, "override_rate": round(overrides / len(made), 3) if made else None,
        "actions": sum(1 for e in entries if e["type"] == "action"),
        "reports": len({e["alert_id"] for e in entries if e["type"] == "report"}),
    }


def one_line(text: str) -> str:
    """Model and log text for the terminal: one line, no control characters."""
    return " ".join(re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(text)).split())


def render_alert(alert: dict, color: bool) -> str:
    cand, priority = alert["candidate"], alert["priority"]
    word = priority.upper()
    if color and priority in COLOURS:
        word = f"\033[{COLOURS[priority]}m{word}\033[0m"
    verdict = f"linked to {alert.get('linked_to')}" if alert["verdict"] == "linked" else alert["verdict"]
    lines = [
        f"{alert['id']}  {word}  {cand['kind']}  {cand['camera_id']} {cand['zone']}  "
        f"first seen {cand['first_seen'][11:19]}",
        f"Agent: {verdict}. {one_line(alert['reason'])}",
        f"Evidence: {one_line(', '.join(alert.get('evidence') or [])) or 'evidence clip missing'}",
    ]
    if alert["verdict"] == "escalate":
        lines.append(f"Proposed action: {proposed_action(cand['kind'], cand['zone'])}")
    return "\n".join(lines)


def decided_line(entry: dict, alert: dict) -> str:
    return (f"decided {entry['ts'][11:16]} (real time) for the alert first seen "
            f"{alert['candidate']['first_seen'][11:19]} (site time)")
