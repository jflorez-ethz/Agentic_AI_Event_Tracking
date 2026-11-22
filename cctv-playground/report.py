#!/usr/bin/env python3
"""Draft the incident report of an approved alert. Paid: one Haiku call, key in .env, about $0.01 or less.

    python report.py --run latest --alert CAM-05-1
    python report.py --run latest --alert A-012 --force    # also for an alert nobody approved

The facts come from the run folder, Haiku writes the text, and code checks it against the facts.
Problems are listed at the bottom of the report.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agentlab import audit, report_writer

ROOT = Path(__file__).resolve().parent


def load_key() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env first.")
    os.environ["ANTHROPIC_API_KEY"] = key  # stray whitespace in .env breaks the provider


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="a run folder, or latest")
    ap.add_argument("--alert", required=True, help="an alert id (A-012) or a candidate id (CAM-05-1)")
    ap.add_argument("--force", action="store_true", help="draft a report although nobody approved the alert")
    ap.add_argument("--model", default=report_writer.REPORT_MODEL, help="with its provider prefix")
    args = ap.parse_args(argv)

    run_dir = audit.resolve_run_dir(args.run, ROOT)
    print(f"run: {run_dir}")
    try:
        report_writer.require_approved(report_writer.collect_facts(run_dir, args.alert), args.force)
    except ValueError as err:
        print(err)
        return 1
    if ":" not in args.model:
        raise SystemExit(f"--model needs a provider prefix, for example {report_writer.REPORT_MODEL}.")
    load_key()  # only now: a refusal needs no key

    try:
        path = report_writer.write_report(run_dir, args.alert, model=args.model, force=args.force)
    except Exception as err:  # noqa: BLE001 - the provider's error is all the user needs
        print(f"Report failed: {type(err).__name__}: {err}")
        return 1
    entry = [e for e in audit.read(run_dir) if e["type"] == "report"][-1]
    print(f"report: {path}")
    print("checks: " + ("no flags" if not entry["flags"] else f"{len(entry['flags'])} flag(s)"))
    for flag in entry["flags"]:
        print(f"  - {flag}")
    cost = "unknown" if entry["cost_usd"] is None else f"{entry['cost_usd']:.4f}"
    print(f"seconds {entry['seconds']}   cost ${cost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
