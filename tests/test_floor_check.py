"""person_on_floor facts (floor_check.py): labelled real cases, rule-by-rule sequences, noise, budgets. Offline."""
import copy
import itertools
import json
import random
import re
from pathlib import Path

import pytest

from security_augmented import floor_check
from security_augmented.floor_check import RULES, check, describe, facts_lines, render_markdown

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {f.stem: json.loads(f.read_text()) for f in sorted((ROOT / "experiments/fall_check/fixtures").glob("*.json"))}
LABELS = json.loads((ROOT / "experiments/fall_check/labels.json").read_text())["cases"]
NOBODY_DOWN = sorted(n for n, fx in FIXTURES.items() if fx["expected"]["status"] != "verified" and fx["expected"].get("reason") != "not_corroborated")
INTERPRETATION = re.compile(r"chut|tomb|fall|fell|brusqu|progressi|sudden|gradual|collaps|accident", re.I)
S = 1_000_000


def replay(fx, transcript=None):
    """ask() answering from a recorded transcript; an unrecorded call fails like a provider error."""
    calls = iter(transcript or fx["transcript"])

    def ask(times_us, phase):
        call = next(calls, None)
        if call is None or call["times_us"] != list(times_us) or call["phase"] != phase:
            raise RuntimeError("no recorded answer for this call")
        return call["inspection_id"], copy.deepcopy(call["frames"])
    return ask


def run(fx, transcript=None):
    (incident,) = check([(f"cand-{fx['case']}", fx["anchor_us"])], replay(fx, transcript),
                        duration_us=fx["duration_us"], aspect=fx["aspect"])
    return incident


def summary(incident, expected):
    got = {"status": incident["status"]}
    if "reason" in expected:
        got["reason"] = incident.get("reason")
    if "arrival_observed" in expected:
        got["arrival_observed"] = incident["arrival"]["observed"]
    if "via" in expected:
        got["via"] = incident["arrival"].get("via")
    if "floor_postures" in expected:
        got["floor_postures"] = [s["posture"] for s in incident["floor_postures"]]
    if "outcome" in expected:
        got["outcome"] = incident["outcome"]["kind"]
    return got


# ---------- frozen rules ----------

def test_rules_are_the_approved_ones():
    assert RULES["version"] == 2 and RULES["min_floor_s"] == 2.0 and RULES["max_floor_displacement"] == 0.10
    assert "kneeling" not in RULES["on_floor"] and set(RULES["on_floor"]) == {"sitting_on_floor", "lying_on_floor"}
    assert RULES["followup"]["max_per_incident"] == 3 and RULES["max_inspections_per_video"] == 6
    assert "max_transition_s" not in RULES  # how the person reached the floor is described, never a condition
    assert len(floor_check.probe_times(10 * S, 60 * S)) == 20


def test_the_probe_question_is_neutral():
    text = floor_check.prompt()
    assert not INTERPRETATION.search(text) and "floor" in text  # 'floor' only names the postures
    for posture in RULES["vocabulary"]:
        assert posture in text


# ---------- labelled real cases (transcripts recorded from labels.json + CAVIAR XML) ----------

@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_known_case_facts(name):
    fx = FIXTURES[name]
    incident = run(fx)
    assert incident == fx["incidents"][0]  # the recorded run is reproduced exactly
    assert summary(incident, fx["expected"]) == fx["expected"]


def test_slump_false_person_down_can_no_longer_be_confirmed():
    """Held-out Rest_SlumpOnFloor 2.52-3.04 s: nobody is on the floor; it stays an alert to review, never verified."""
    incident = run(FIXTURES["slump_false"])
    assert (incident["status"], incident["reason"]) == ("to_review", "upright_throughout")
    assert "debout tout du long" in facts_lines(incident, "fr")[0]


def test_measured_facts_of_the_real_cases():
    fight = run(FIXTURES["fight_true"])
    assert fight["arrival"] == {"observed": True, "upright_us": 12_799_700, "seconds": 0.24, "via": []}
    assert fight["outcome"]["kind"] == "stood_up" and fight["outcome"]["via"] == ["kneeling", "bending"]
    fall = run(FIXTURES["fall_true"])
    assert fall["arrival"]["seconds"] == 1.24 and fall["arrival"]["via"] == ["bending", "kneeling"]
    assert fall["floor_seconds"] >= 8.0 and fall["followup_still_on_floor"]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_no_interpretation_words(name):
    incident = run(FIXTURES[name])
    for lang in ("fr", "en"):
        for line in facts_lines(incident, lang):
            assert not INTERPRETATION.search(line), line
    assert not INTERPRETATION.search(render_markdown([incident]))


# ---------- noise injected into the recorded answers ----------

def noisy(fx, changes):
    """changes: [(call index, frame index, person id, posture)]."""
    t = copy.deepcopy(fx["transcript"])
    for c, f, pid, label in changes:
        for p in t[c]["frames"][f]["persons"]:
            if p["id"] == pid:
                p["posture"] = label
    return t


def slots(fx):
    return [(0, f, p["id"]) for f, frame in enumerate(fx["transcript"][0]["frames"]) for p in frame["persons"]]


@pytest.mark.parametrize("k", [1, 2])
def test_isolated_wrong_floor_labels_never_verify(k):
    for name in NOBODY_DOWN:
        fx = FIXTURES[name]
        for combo in itertools.combinations(slots(fx), k):
            for label in RULES["on_floor"]:
                incident = run(fx, noisy(fx, [(*s, label) for s in combo]))
                assert incident["status"] != "verified", (name, combo, label)


def test_short_runs_of_wrong_floor_labels_never_verify():
    for name in NOBODY_DOWN:
        fx = FIXTURES[name]
        focal = "P" + LABELS[name]["focal"]
        frames = len(fx["transcript"][0]["frames"])
        for length in range(1, 6):
            for start in range(0, frames - length + 1):
                changes = [(0, f, focal, "lying_on_floor") for f in range(start, start + length)]
                assert run(fx, noisy(fx, changes))["status"] != "verified", (name, start, length)


@pytest.mark.parametrize("p", [0.05, 0.10, 0.20])
def test_random_label_noise_never_verifies_when_nobody_is_down(p):
    rng = random.Random(4321)
    for _ in range(120):
        for name in NOBODY_DOWN:
            fx = FIXTURES[name]
            changes = [(*s, rng.choice(RULES["vocabulary"])) for s in slots(fx) if rng.random() < p]
            assert run(fx, noisy(fx, changes))["status"] != "verified", (name, changes)


@pytest.mark.parametrize("name", ["fall_true", "wiggle_true", "fight_true"])
@pytest.mark.parametrize("label", ["bending", "kneeling", "sitting_on_seat"])
def test_real_cases_survive_one_wrong_non_upright_label(name, label):
    fx = FIXTURES[name]
    focal = "P" + LABELS[name]["focal"]
    for f in range(len(fx["transcript"][0]["frames"])):
        if any(p["id"] == focal for p in fx["transcript"][0]["frames"][f]["persons"]):
            assert run(fx, noisy(fx, [(0, f, focal, label)]))["status"] == "verified", (f, label)


# ---------- rule by rule, on synthetic sequences ----------

def seq(labels, *, t0=8.0, step=0.42, moves=0.0, source="probe", x=0.5, y=0.5):
    return [(round((t0 + i * step) * S), label, None if label == "not_visible" else min(1.0, x + moves * i), y, source)
            for i, label in enumerate(labels)]


ANCHOR = 9 * S
FLOOR = ["standing"] * 3 + ["sitting_on_floor"] + ["lying_on_floor"] * 8


def facts(sequence, anchor=ANCHOR, **kw):
    return describe(sequence, anchor, aspect=0.75, video_end_us=60 * S, **kw)


def test_verified_with_standing_seen_before():
    r = facts(seq(FLOOR))
    assert r["status"] == "verified" and r["arrival"]["observed"] and r["floor_postures"][0]["posture"] == "sitting_on_floor"


def test_kneeling_after_an_on_the_floor_report_is_an_alert_with_what_was_seen():
    r = {**facts(seq(["standing"] * 3 + ["kneeling"] * 12)), "anchor_us": ANCHOR}
    assert (r["status"], r["reason"]) == ("to_review", "kneeling") and floor_check.alerting([r]) == [r]
    lines = facts_lines(r, "fr")
    assert "à genoux, personne au sol" in lines[0] and lines[1].startswith("Ce que l'inspection fine a vu : debout")


def test_a_seat_after_an_on_the_floor_report_is_an_alert_with_what_was_seen():
    r = {**facts(seq(["standing"] * 3 + ["sitting_on_seat"] * 12)), "anchor_us": ANCHOR}
    assert (r["status"], r["reason"]) == ("to_review", "seated") and floor_check.alerting([r]) == [r]
    assert "assise sur un siège 00:09.26–00:13.88" in facts_lines(r, "fr")[1]


def test_slow_arrival_is_described_not_refused():
    r = facts(seq(["standing"] * 3 + ["kneeling"] * 6 + ["sitting_on_floor"] * 8), anchor=12 * S)
    assert r["status"] == "verified" and r["arrival"]["seconds"] > 2.5 and r["arrival"]["via"] == ["kneeling"]


def test_already_on_the_floor_needs_a_followup():
    down = seq(["lying_on_floor"] * 12)
    r = facts(down)
    assert (r["status"], r["reason"], r["arrival"]["why"]) == ("to_review", "not_corroborated", "already_on_floor")
    later = down + seq(["lying_on_floor"] * 3, t0=14.0, step=1.0, source="followup")
    assert facts(later)["status"] == "verified"


def test_too_short_and_moving():
    assert facts(seq(["standing"] * 3 + ["lying_on_floor"] * 3 + ["standing"] * 6))["reason"] == "floor_too_short"
    assert facts(seq(FLOOR, moves=0.03))["reason"] == "moving_on_floor"


def test_far_in_time_from_the_candidate():
    assert facts(seq(FLOOR), anchor=30 * S)["reason"] == "not_near_candidate"


def test_outcomes():
    up = facts(seq(FLOOR + ["kneeling", "standing"]))
    assert up["outcome"]["kind"] == "stood_up" and up["outcome"]["via"] == ["kneeling"]
    end = describe(seq(FLOOR), ANCHOR, aspect=0.75, video_end_us=seq(FLOOR)[-1][0] + 500_000)
    assert end["outcome"]["kind"] == "on_floor_at_end"
    stopped = facts(seq(FLOOR), followup_stopped=True)
    assert stopped["outcome"]["kind"] == "followup_stopped" and "suivi arrêté" in facts_lines(stopped, "fr")[-1]


# ---------- orchestration: follow-ups, linking, merging, budgets, failures ----------

def asker(posture_at, *, others=()):
    """Simulated probe: one person at (0.5, 0.5) with posture_at(t_s); optional other persons [(x, y, posture)]."""
    calls = []

    def ask(times_us, phase):
        calls.append((phase, list(times_us)))
        frames = [{"t_us": t, "display_index": i, "frame_id": f"f{t}",
                   "persons": [{"id": "P1", "posture": posture_at(t / S), "x": 0.5, "y": 0.5},
                               *({"id": f"P{n + 2}", "posture": p, "x": x, "y": y} for n, (x, y, p) in enumerate(others))]}
                  for i, t in enumerate(times_us)]
        return f"insp-{len(calls)}", frames
    return ask, calls


def test_followups_measure_time_on_the_floor_and_standing_up():
    ask, calls = asker(lambda t: "standing" if t < 9 else "lying_on_floor" if t < 40 else "standing")
    (i,) = check([("o1", 9 * S)], ask, duration_us=120 * S, aspect=0.75)
    assert [c[0] for c in calls] == ["floor_probe", "floor_followup", "floor_followup"]
    assert i["status"] == "verified" and i["outcome"]["kind"] == "stood_up" and 40 * S <= i["outcome"]["at_us"] < 42 * S


def test_followups_stop_after_three():
    ask, calls = asker(lambda t: "standing" if t < 9 else "lying_on_floor")
    (i,) = check([("o1", 9 * S)], ask, duration_us=600 * S, aspect=0.75)
    assert len(calls) == 1 + RULES["followup"]["max_per_incident"]
    assert i["outcome"]["kind"] == "followup_stopped" and i["floor_seconds"] > 60


def test_followup_links_by_position_not_by_id():
    ask, _ = asker(lambda t: "standing" if t < 9 else "lying_on_floor" if t < 15 else "not_visible_here",
                   others=[(0.95, 0.95, "standing")])

    def patched(times_us, phase):  # after 15 s the person on the floor is no longer listed; a far person stays
        inspection, frames = ask(times_us, phase)
        for f in frames:
            f["persons"] = [p for p in f["persons"] if p["posture"] != "not_visible_here"]
        return inspection, frames
    (i,) = check([("o1", 9 * S)], patched, duration_us=60 * S, aspect=0.75)
    assert i["outcome"]["kind"] == "last_seen" and i["outcome"]["posture"] == "not_visible"


def test_nearby_candidates_merge_into_one_incident():
    ask, calls = asker(lambda t: "standing" if t < 9 else "lying_on_floor" if t < 30 else "standing")
    incidents = check([("o1", 9 * S), ("o2", 20 * S), ("o3", 29 * S)], ask, duration_us=60 * S, aspect=0.75)
    assert len(incidents) == 1 and incidents[0]["observation_ids"] == ["o1", "o2", "o3"]


def test_video_budget_of_six_inspections():
    ask, calls = asker(lambda t: "standing")
    incidents = check([(f"o{n}", n * 20 * S) for n in range(1, 9)], ask, duration_us=400 * S, aspect=0.75)
    assert len(calls) == RULES["max_inspections_per_video"]
    assert [i["reason"] for i in incidents[6:]] == ["budget_exhausted"] * 2
    assert all(i["status"] == "to_review" for i in incidents)  # never dismissed, never verified


def test_failed_probe_leaves_an_alert_to_review():
    def ask(times_us, phase):
        raise RuntimeError("HTTP 503")
    (i,) = check([("o1", 9 * S)], ask, duration_us=60 * S, aspect=0.75)
    assert (i["status"], i["reason"]) == ("to_review", "probe_failed") and floor_check.alerting([i]) == [i]
