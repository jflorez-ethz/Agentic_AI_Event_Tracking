#!/usr/bin/env python3
"""Review an agent run: approve or dismiss what it escalated, check what it closed. Free, no model calls.

    python review.py --run latest                  # the pending alerts, one at a time
    python review.py --run latest --closed         # the alerts the agent closed itself
    python review.py --run latest --decide CAM-05-1=approve --decide "CAM-04-2=dismiss:Kneeling, not a fall"
    python review.py --run latest --summary

An approval logs a simulated dispatch. Nothing here contacts anyone.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from agentlab import review as logic
from agentlab.audit import resolve_run_dir
from fakecctv.alerts import AlertStore

ROOT = Path(__file__).resolve().parent
PENDING_KEYS = {"a": "approve", "d": "dismiss"}
CLOSED_KEYS = {"c": "confirm", "r": "reopen"}


def parse_decide(value: str) -> tuple[str, str, str]:
    ref, _, rest = value.partition("=")
    decision, colon, reason = rest.partition(":")
    ref, reason = ref.strip(), reason.strip()
    if decision in logic.NEEDS_REASON:
        ok = bool(reason)
    else:
        ok = decision in logic.KIT_WORDS and not colon
    if not ref or not ok:
        raise argparse.ArgumentTypeError(
            f"{value!r}: use REF=approve, REF=confirm, REF=dismiss:REASON or REF=reopen:REASON")
    return ref, decision, reason


def open_clip(run_dir: Path, alert: dict) -> None:
    clips = [run_dir / p for p in alert.get("evidence") or [] if p.lower().endswith(".mp4")]
    if not clips or not clips[0].is_file():
        print("evidence clip missing")
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, str(clips[0].resolve())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as err:
        print(f"Could not open the clip: {err}")


def screen(run_dir: Path, closed: bool, reviewer: str) -> None:
    queue = logic.closed(run_dir) if closed else logic.pending(run_dir)
    if not queue:
        print("No closed alerts left to check." if closed else "No alerts waiting for a decision.")
        return
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    keys = CLOSED_KEYS if closed else PENDING_KEYS
    choices = [f"[{key}] {decision}" for key, decision in keys.items()]
    menu = "   ".join(choices + ["[o] open clip", "[s] skip", "[q] quit"])

    for alert in queue:
        print("\n" + logic.render_alert(alert, color))
        while True:
            key = input(f"{menu}\n> ").strip().lower()
            if key == "q":
                return
            if key == "s":
                break
            if key == "o":
                open_clip(run_dir, alert)
            elif key in keys:
                reason = input("Reason: ") if keys[key] in logic.NEEDS_REASON else ""
                try:
                    entry = logic.decide(run_dir, alert["id"], keys[key], reason, reviewer)
                except ValueError as err:
                    print(err)
                    continue
                print(logic.decided_line(entry, alert))
                break


def apply(run_dir: Path, wanted: list[tuple[str, str, str]], reviewer: str) -> int:
    alerts, code = AlertStore(run_dir).all(), 0
    for ref, decision, reason in wanted:
        try:
            entry = logic.decide(run_dir, ref, decision, reason, reviewer)
        except ValueError as err:
            print(err)
            code = 1
            continue
        print(f"{entry['alert_id']} {decision}: {logic.decided_line(entry, logic.find_alert(alerts, ref))}")
    return code


def print_summary(run_dir: Path) -> None:
    for key, value in logic.summary(run_dir).items():
        if key == "override_rate":
            value = "- (no decisions yet)" if value is None else f"{100 * value:.1f}%"
        print(f"{key.replace('_', ' '):<18} {value}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a run folder, or latest")
    ap.add_argument("--closed", action="store_true", help="go through the alerts the agent closed itself")
    ap.add_argument("--decide", action="append", type=parse_decide, default=[], metavar="REF=DECISION[:REASON]",
                    help="decide without the screen; repeatable")
    ap.add_argument("--reviewer", default=logic.REVIEWER)
    ap.add_argument("--summary", action="store_true", help="print the audit counts and the override rate")
    args = ap.parse_args(argv)  # every --decide is checked here, before any is applied

    run_dir = resolve_run_dir(args.run, ROOT)
    print(f"run: {run_dir}")
    code = apply(run_dir, args.decide, args.reviewer)
    if args.summary:
        print_summary(run_dir)
    elif not args.decide:
        try:
            screen(run_dir, args.closed, args.reviewer)
        except (EOFError, KeyboardInterrupt):
            print()
    return code


if __name__ == "__main__":
    sys.exit(main())
