"""Residual risk of the doubt signals (rules v4), offline: sustained wrong "lying" labels when nobody is on the floor.

    .venv/bin/python experiments/fall_check/residual_risk.py

For each labelled case where nobody is on the floor, 6 to 20 consecutive close-check frames of the person at the
candidate are relabelled lying_on_floor (every start position). A card with no doubt signal would be shown to the
guard without the "Look closely" badge. Two follow-up hypotheses: the follow-up shows the truth (people standing),
or it repeats the error (the person still lying), or it fails.
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import test_floor_check as t  # noqa: E402  (reuses the fixtures, replay and noise helpers)


def lying_followups(fx, transcript):
    ask = t.replay(fx, transcript, standing_followups=True)

    def wrong(times_us, phase):
        inspection, frames = ask(times_us, phase)
        if phase == "floor_followup":
            for f in frames:
                for p in f["persons"]:
                    p["posture"] = "lying_on_floor"
        return inspection, frames
    return wrong


def main():
    from security_augmented.floor_check import check
    results = {"truthful follow-up": Counter(), "follow-up repeats the error": Counter(), "follow-up fails": Counter()}
    total = 0
    for name in t.NOBODY_DOWN:
        fx = t.FIXTURES[name]
        focal = "P" + t.LABELS[name]["focal"]
        n = len(fx["transcript"][0]["frames"])
        for length in range(6, 21):
            for start in range(0, n - length + 1):
                tr = t.noisy(fx, [(0, f, focal, "lying_on_floor") for f in range(start, start + length)])
                total += 1
                cand = f"cand-{name}"
                claimed = set() if fx["first_look"] == "suspected" else {cand}
                for label, ask in (("truthful follow-up", t.replay(fx, tr, standing_followups=True)),
                                   ("follow-up repeats the error", lying_followups(fx, tr)),
                                   ("follow-up fails", t.replay(fx, tr))):
                    (i,) = check([(cand, fx["anchor_us"])], ask, duration_us=fx["duration_us"], aspect=fx["aspect"],
                                 frame_size=tuple(fx["frame_size"]), claimed=claimed)
                    results[label]["unmarked" if not i["doubt_signals"] else "marked"] += 1
                    for s in i["doubt_signals"]:
                        results[label]["signal:" + s["code"]] += 1
    print(f"{total} fake runs (7 cases where nobody is on the floor, 6-20 consecutive wrong 'lying' labels)")
    for label, c in results.items():
        signals = ", ".join(f"{k[7:]} {v}" for k, v in c.most_common() if k.startswith("signal:"))
        print(f"{label:30s} no doubt signal: {c['unmarked']}/{total} ({c['unmarked'] / total:.0%}); signals seen: {signals}")


if __name__ == "__main__":
    main()
