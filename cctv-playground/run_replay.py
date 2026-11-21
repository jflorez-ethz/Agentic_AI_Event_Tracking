#!/usr/bin/env python3
"""The replay runner: the "live" side of the demo.

    python run_replay.py --reset            # start the night over (clears alerts)
    python run_replay.py --reset --play --speed 8

Every half second it reads the replay clock, asks the detector what is new up to "now",
and hands each candidate to triage, which calls the agent tools and writes an alert to
the inbox. The Streamlit screen (app.py) reads the same clock and the same inbox.

Play, pause, speed and jumps can be controlled from the screen or from here.
"""
from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from fakecctv.alerts import AlertStore
from fakecctv.clock import ReplayClock
from fakecctv.context import SiteContext
from fakecctv.detector import OracleDetector
from fakecctv.recorder import Recorder
from fakecctv.site import load_site
from fakecctv.tools import AgentTools
from fakecctv.triage_stub import triage

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default=str(ROOT / "site" / "index.json"))
    ap.add_argument("--runtime", default=str(ROOT / "runtime"))
    ap.add_argument("--reset", action="store_true", help="clock back to the site start, inbox and clip cache cleared")
    ap.add_argument("--play", action="store_true", help="start the clock")
    ap.add_argument("--speed", type=float, help="replay speed, e.g. 1, 4, 16")
    ap.add_argument("--delay", type=float, default=10.0, help="seconds of footage the detector needs before it fires")
    args = ap.parse_args()

    runtime = Path(args.runtime)
    site = load_site(args.index)
    clock = ReplayClock(site.start, site.end, runtime / "clock.json")
    store = AlertStore(runtime)
    if args.reset:
        clock.reset()
        store.clear()
        shutil.rmtree(runtime / "clips", ignore_errors=True)
    if args.speed:
        clock.set_speed(args.speed)
    if args.play:
        clock.play()

    recorder = Recorder(site, clock, runtime / "clips")
    context = SiteContext(site, clock)
    detector = OracleDetector(site, delay_s=args.delay, already_fired=store.handled_candidates())

    print(f"{site.name}: {len(site.cameras)} cameras, {site.start:%H:%M:%S} to {site.end:%H:%M:%S}.")
    print(f"Clock at {clock.now():%H:%M:%S}, {'paused' if clock.paused else f'playing at {clock.speed:g}x'}. "
          "Press Play on the screen (streamlit run app.py). Ctrl+C to stop.")
    last_report = 0.0
    try:
        while True:
            now = clock.now()
            for candidate in detector.poll(now):
                tools = AgentTools(recorder, context)
                verdict = triage(candidate, tools, store.open_alerts())
                alert = store.add(candidate, verdict, tools.trace, created_site_time=clock.now())
                print(f"[{now:%H:%M:%S}] {alert['id']} {candidate['camera_id']} {candidate['kind']}: "
                      f"{alert['verdict'].upper()} - {alert['reason']}")
            if time.time() - last_report > 30:
                state = "paused" if clock.paused else f"{clock.speed:g}x"
                print(f"  site time {now:%H:%M:%S} ({state})")
                last_report = time.time()
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
