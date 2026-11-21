#!/usr/bin/env python3
"""Batch evaluation: the same detector, triage and tools, without waiting for the clock.

    python evaluate.py
    python evaluate.py --index site/index.json --json results.json

An in-memory clock jumps straight to each detection time, so a 30-minute site runs in
seconds. The tools still refuse footage after that moment, so the result is what the
live replay would have produced. The labels are used only here, to score the verdicts.

This is the seed of the KPI script (task B7): add timings, report effort and cost as
those pieces arrive.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path

from fakecctv.alerts import AlertStore
from fakecctv.clock import ReplayClock
from fakecctv.context import SiteContext
from fakecctv.detector import OracleDetector
from fakecctv.recorder import Recorder
from fakecctv.site import load_site
from fakecctv.tools import AgentTools
from fakecctv.triage_stub import NEVER_DISMISS, triage

ROOT = Path(__file__).resolve().parent


def run(index: str, delay_s: float = 10.0) -> dict:
    site = load_site(index)
    clock = ReplayClock(site.start, site.end)  # in memory
    work = Path(tempfile.mkdtemp(prefix="fakecctv-eval-"))
    recorder = Recorder(site, clock, work / "clips")
    context = SiteContext(site, clock)
    store = AlertStore(work)
    detector = OracleDetector(site, delay_s=delay_s)

    for label in sorted(site.labels, key=lambda l: l.start):
        clock.jump(min(label.start + detector.delay, site.end))
        for candidate in detector.poll(clock.now()):
            tools = AgentTools(recorder, context)
            verdict = triage(candidate, tools, store.open_alerts())
            store.add(candidate, verdict, tools.trace, created_site_time=clock.now())

    alerts = {a["candidate"]["candidate_id"]: a for a in store.all()}
    by_id = {a["id"]: a for a in alerts.values()}
    rows = []
    for label in sorted(site.labels, key=lambda l: l.start):
        a = alerts.get(label.id)
        verdict = a["verdict"] if a else "missed by detector"
        reached = bool(a) and (a["verdict"] == "escalate" or
                               (a["verdict"] == "linked" and by_id.get(a.get("linked_to"), {}).get("verdict") == "escalate"))
        rows.append({
            "event": label.id, "camera": label.camera_id, "type": label.type,
            "first_seen": f"{label.start:%H:%M:%S}", "real": label.real, "verdict": verdict,
            "reached_a_person": reached, "correct": reached == label.real,
            "time_to_alert_s": (datetime.fromisoformat(a["created"]) - label.start).total_seconds() if a else None,
        })

    candidates = len(alerts)
    escalated = sum(1 for a in alerts.values() if a["verdict"] == "escalate")
    real = [r for r in rows if r["real"]]
    kept = sum(1 for r in real if r["reached_a_person"])
    missed_critical = sum(1 for r in real if r["type"] in NEVER_DISMISS and not r["reached_a_person"])
    tta = [r["time_to_alert_s"] for r in rows if r["reached_a_person"] and r["time_to_alert_s"] is not None]
    summary = {
        "detector_events": candidates,
        "alerts_sent_to_a_person": escalated,
        "alerts_reduction_pct": round(100 * (1 - escalated / candidates), 1) if candidates else None,
        "real_events_kept_pct": round(100 * kept / len(real), 1) if real else None,
        "missed_critical_events": missed_critical,
        "median_time_to_alert_s": sorted(tta)[len(tta) // 2] if tta else None,
    }
    return {"summary": summary, "events": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default=str(ROOT / "site" / "index.json"))
    ap.add_argument("--delay", type=float, default=10.0)
    ap.add_argument("--json", help="also write the results to this file")
    args = ap.parse_args()
    result = run(args.index, args.delay)

    print(f"{'event':<10} {'type':<20} {'seen':<9} {'real':<6} {'verdict':<10} {'to person':<10} ok")
    for r in result["events"]:
        print(f"{r['event']:<10} {r['type']:<20} {r['first_seen']:<9} {str(r['real']):<6} "
              f"{r['verdict']:<10} {str(r['reached_a_person']):<10} {'yes' if r['correct'] else 'NO'}")
    print()
    for k, v in result["summary"].items():
        print(f"{k.replace('_', ' '):<28} {v}")
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
