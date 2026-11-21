#!/usr/bin/env python3
"""Batch evaluation: the same detector, triage and tools, without waiting for the clock.

    python evaluate.py
    python evaluate.py --index site/index.json --json results.json
    python evaluate.py --triage agent          # step 5 agent (paid: Claude API, key in .env)

An in-memory clock jumps straight to each detection time, so a 30-minute site runs in
seconds. The tools still refuse footage after that moment, so the result is what the
live replay would have produced. The labels are used only here, to score the verdicts.

This is the seed of the KPI script (task B7): add timings, report effort and cost as
those pieces arrive.
"""
from __future__ import annotations

import argparse
import json
import os
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
AGENT_MODEL = "anthropic:claude-haiku-5-5"
STAT_COLUMNS = ("cost_usd", "requests", "tool_calls", "tool_errors", "overrides")


def run(index: str, delay_s: float = 10.0, triage_fn=None) -> dict:
    """Replay the detector and triage every candidate, one at a time (the open alerts depend on order).

    triage_fn defaults to the stub. A triage_fn with a `stats` dict (agentlab.triage_agent.AgentTriage)
    adds cost and tool columns to the rows and cost totals to the summary."""
    triage_fn = triage_fn or triage
    stats = getattr(triage_fn, "stats", None)
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
            verdict = triage_fn(candidate, tools, store.open_alerts())
            store.add(candidate, verdict, tools.trace, created_site_time=clock.now())

    alerts = {a["candidate"]["candidate_id"]: a for a in store.all()}
    by_id = {a["id"]: a for a in alerts.values()}
    rows = []
    for label in sorted(site.labels, key=lambda l: l.start):
        a = alerts.get(label.id)
        verdict = a["verdict"] if a else "missed by detector"
        reached = bool(a) and (a["verdict"] == "escalate" or
                               (a["verdict"] == "linked" and by_id.get(a.get("linked_to"), {}).get("verdict") == "escalate"))
        row = {
            "event": label.id, "camera": label.camera_id, "type": label.type,
            "first_seen": f"{label.start:%H:%M:%S}", "real": label.real, "verdict": verdict,
            "reached_a_person": reached, "correct": reached == label.real,
            "time_to_alert_s": (datetime.fromisoformat(a["created"]) - label.start).total_seconds() if a else None,
        }
        if stats is not None:
            s = stats.get(label.id) if a else None
            row.update({k: (s or {}).get(k) for k in STAT_COLUMNS})
            # The replay clock stands still while the agent works: add its own seconds (KPI 3).
            row["triage_s"] = (s or {}).get("seconds")
            if row["time_to_alert_s"] is not None and row["triage_s"] is not None:
                row["time_to_alert_s"] = round(row["time_to_alert_s"] + row["triage_s"], 2)
        rows.append(row)

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
    if stats is not None:
        costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
        summary["total_cost_usd"] = round(sum(costs), 6)
        summary["mean_cost_per_alert_usd"] = round(sum(costs) / len(costs), 6) if costs else None
    return {"summary": summary, "events": rows}


def make_agent(model: str):
    """The step 5 triage agent, with the API key from .env and a run folder for this run."""
    from dotenv import load_dotenv

    if ":" not in model:
        raise SystemExit(f"--model needs a provider prefix, for example {AGENT_MODEL}.")
    load_dotenv(ROOT / ".env", override=True)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env first.")
    os.environ["ANTHROPIC_API_KEY"] = key  # stray whitespace in .env breaks the provider

    from agentlab.triage_agent import AgentTriage
    return AgentTriage(model, run_dir=run_dir_for(datetime.now()))


def run_dir_for(now: datetime) -> Path:
    """runs/triage/<YYYYmmdd-HHMMSS>: to the second, so two runs in the same minute get their own folder."""
    return ROOT / "runs" / "triage" / now.strftime("%Y%m%d-%H%M%S")


def print_table(result: dict, run_dir: Path | None = None) -> None:
    rows = result["events"]
    extra = any("cost_usd" in r for r in rows)
    head = f"{'event':<10} {'type':<20} {'seen':<9} {'real':<6} {'verdict':<10} {'to person':<10} ok"
    if extra:
        head += f"   {'cost $':>8} {'agent s':>7} {'req':>4} {'tools':>5} {'err':>4}  overrides"
    print(head)
    for r in rows:
        line = (f"{r['event']:<10} {r['type']:<20} {r['first_seen']:<9} {str(r['real']):<6} "
                f"{r['verdict']:<10} {str(r['reached_a_person']):<10} {'yes' if r['correct'] else 'NO'}")
        if extra and r.get("cost_usd") is not None:
            line = f"{line:<76}{r['cost_usd']:>8.4f} {r.get('triage_s') or 0:>7.1f} {r['requests']:>4} " \
                   f"{r['tool_calls']:>5} {r['tool_errors']:>4}  " \
                   f"{', '.join(r['overrides']) or '-'}"
        print(line)
    print()
    for k, v in result["summary"].items():
        print(f"{k.replace('_', ' '):<28} {v}")
    if run_dir:
        print(f"\nrun files: {run_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default=str(ROOT / "site" / "index.json"))
    ap.add_argument("--delay", type=float, default=10.0)
    ap.add_argument("--json", help="also write the results to this file")
    ap.add_argument("--triage", choices=["stub", "agent"], default="stub",
                    help="stub: the kit's fixed rules (free); agent: the step 5 agent (paid)")
    ap.add_argument("--model", default=AGENT_MODEL, help="the agent's brain, with its provider prefix")
    args = ap.parse_args()
    agent = make_agent(args.model) if args.triage == "agent" else None
    result = run(args.index, args.delay, triage_fn=agent)

    print_table(result, agent.run_dir if agent else None)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
