"""Regression tests for the person_fell decision (offline; no model call, no live run)."""
import copy
import itertools
import json
import random
from pathlib import Path

import pytest

import decision
from decision import RULES, decide, probe_times

HERE = Path(__file__).resolve().parent
FX = {f.stem: json.loads(f.read_text()) for f in sorted((HERE / "fixtures").glob("*.json"))}
LABELS = json.loads((HERE / "labels.json").read_text())["cases"]
SOMEONE_DOWN = {"fall_true", "wiggle_true", "fight_true", "slump_true_slow"}
NOBODY_DOWN = sorted(set(FX) - SOMEONE_DOWN)
CONFIRMABLE = sorted(k for k, v in FX.items() if v["expected"]["verdict"] == "supported")


def relabel(fx, changes):
    probe = copy.deepcopy(fx["probe"])
    for i, pid, label in changes:
        for p in probe["frames"][i]["persons"]:
            if p["id"] == pid:
                p["posture"] = label
                if label != "not_visible" and "x" not in p:
                    p["x"], p["y"] = 0.5, 0.5
    return probe


def focal(name):
    return "P" + LABELS[name]["focal"]


# ---------- the frozen thresholds (a change must be deliberate) ----------

def test_rules_are_the_approved_ones():
    assert RULES["max_transition_s"] == 2.5 and RULES["min_ground_s"] == 2.0
    assert RULES["max_ground_displacement"] == 0.10
    assert "kneeling" not in RULES["on_ground"] and set(RULES["on_ground"]) == {"sitting_on_floor", "lying_on_floor"}
    assert RULES["per_video_budget"] == {"probes_per_candidate": 1, "max_probes_per_video": 3}


def test_probe_plan_is_20_frames_8_before_12_after():
    t = probe_times(10.0)
    assert len(t) == 20
    assert t[0] == pytest.approx(8.0) and t[7] == pytest.approx(9.75) and t[8] == pytest.approx(10.0)
    assert t[-1] == pytest.approx(10.0 + 11 * 0.42)


# ---------- known cases, labelled on the images ----------

@pytest.mark.parametrize("name", sorted(FX))
def test_known_case_outcome(name):
    fx = FX[name]
    d = decide(fx["probe"], fx["candidate"])
    assert (d["verdict"], d["reason"]) == (fx["expected"]["verdict"], fx["expected"]["reason"])


def test_slump_false_fall_can_no_longer_be_confirmed():
    """The held-out false 'person down' (2.52-3.04 s): nobody is on the ground in the dense probe."""
    fx = FX["slump_false"]
    assert decide(fx["probe"], fx["candidate"])["verdict"] == "insufficient"
    # Even if the probe repeats Perception's original mistake on the 'after' frame (and its neighbour).
    after = min(range(20), key=lambda i: abs(fx["probe"]["frames"][i]["t"] - fx["candidate"]["t_after"]))
    for changes in ([(after, "P0", "lying_on_floor")], [(after, "P0", "lying_on_floor"), (after + 1, "P0", "lying_on_floor")]):
        assert decide(relabel(fx, changes), fx["candidate"])["verdict"] == "insufficient"
    # And without a probe there is no confirmation at all.
    assert decide(None, fx["candidate"])["verdict"] == "insufficient"


# ---------- noise injected into the probe answers ----------

@pytest.mark.parametrize("k", [1, 2])
def test_isolated_wrong_ground_labels_never_confirm(k):
    for name in NOBODY_DOWN:
        fx = FX[name]
        slots = [(i, p["id"]) for i, f in enumerate(fx["probe"]["frames"]) for p in f["persons"]]
        for combo in itertools.combinations(slots, k):
            for label in ("lying_on_floor", "sitting_on_floor"):
                d = decide(relabel(fx, [(i, pid, label) for i, pid in combo]), fx["candidate"])
                assert d["verdict"] == "insufficient", (name, combo, label)


def test_short_runs_of_wrong_ground_labels_never_confirm():
    """Up to 5 consecutive wrong 'lying' frames on the person at the candidate never confirm (cover < 2 s)."""
    for name in NOBODY_DOWN:
        fx = FX[name]
        for length in range(1, 6):
            for start in range(0, 21 - length):
                d = decide(relabel(fx, [(i, focal(name), "lying_on_floor") for i in range(start, start + length)]), fx["candidate"])
                assert d["verdict"] == "insufficient", (name, start, length)


@pytest.mark.parametrize("p", [0.05, 0.10, 0.20])
def test_random_label_noise_never_confirms_when_nobody_is_down(p):
    rng = random.Random(1234)
    for _ in range(150):
        for name in NOBODY_DOWN:
            fx = FX[name]
            changes = [(i, q["id"], rng.choice(RULES["vocabulary"]))
                       for i, f in enumerate(fx["probe"]["frames"]) for q in f["persons"] if rng.random() < p]
            assert decide(relabel(fx, changes), fx["candidate"])["verdict"] == "insufficient", (name, changes)


@pytest.mark.parametrize("name", CONFIRMABLE)
@pytest.mark.parametrize("label", ["bending", "kneeling", "sitting_on_seat", "not_visible"])
def test_true_falls_survive_one_wrong_non_upright_label(name, label):
    fx = FX[name]
    for i in range(20):
        assert decide(relabel(fx, [(i, focal(name), label)]), fx["candidate"])["verdict"] == "supported", (i, label)


def test_a_wrong_standing_label_can_only_withhold_confirmation():
    """A single 'standing' inside the ground run ends it: the safe side (alert to review), never an error."""
    for name in CONFIRMABLE:
        for i in range(20):
            d = decide(relabel(FX[name], [(i, focal(name), "standing")]), FX[name]["candidate"])
            assert d["verdict"] in ("supported", "insufficient") and d["reason"] in RULES["reasons_in_priority_order"]


# ---------- rule-by-rule synthetic sequences ----------

def seq(labels, *, t0=8.0, step=0.42, moves=0.0, pid="P1", x=0.5, y=0.5):
    frames = []
    for i, label in enumerate(labels):
        p = {"id": pid, "posture": label}
        if label != "not_visible":
            p.update(x=min(1.0, x + moves * i), y=y)
        frames.append({"t": round(t0 + i * step, 4), "persons": [p]})
    return {"aspect": 0.75, "frames": frames}


CAND = {"t_after": 9.0, "x": 0.5, "y": 0.5}
FALL = ["standing"] * 3 + ["sitting_on_floor"] + ["lying_on_floor"] * 8


def test_clean_fall_confirms():
    assert decide(seq(FALL), CAND)["reason"] == "confirmed"


def test_persistent_kneeling_is_never_a_fall():
    d = decide(seq(["standing"] * 3 + ["kneeling"] * 12), CAND)
    assert (d["verdict"], d["reason"]) == ("insufficient", "kneeling_not_ground")


def test_sitting_on_a_seat_is_not_the_ground():
    assert decide(seq(["standing"] * 3 + ["sitting_on_seat"] * 12), CAND)["reason"] == "seated"


def test_slow_transition_is_not_confirmed():
    d = decide(seq(["standing"] * 3 + ["kneeling"] * 6 + ["lying_on_floor"] * 8), {"t_after": 12.0})
    assert d["reason"] == "transition_too_slow"


def test_too_short_on_the_ground():
    d = decide(seq(["standing"] * 3 + ["lying_on_floor"] * 3 + ["standing"] * 6), CAND)
    assert d["reason"] == "ground_too_short"


def test_moving_while_on_the_ground():
    assert decide(seq(FALL, moves=0.03), CAND)["reason"] == "moving_on_ground"


def test_already_down_at_the_start():
    assert decide(seq(["lying_on_floor"] * 12), CAND)["reason"] == "no_upright_before"


def test_upright_throughout_blocks():
    assert decide(seq(["standing"] * 12), CAND)["reason"] == "upright_throughout"


def test_far_from_the_candidate():
    assert decide(seq(FALL), {"t_after": 9.0, "x": 0.95, "y": 0.95})["reason"] == "no_person_near"
    assert decide(seq(FALL), {"t_after": 30.0, "x": 0.5, "y": 0.5})["reason"] == "no_person_near"


def test_any_nearby_person_with_the_pattern_confirms():
    probe = seq(FALL)
    for f in probe["frames"]:
        f["persons"].append({"id": "P2", "posture": "standing", "x": 0.55, "y": 0.5})
    assert decide(probe, CAND)["person"] == "P1"


@pytest.mark.parametrize("probe, detail", [
    ({"aspect": 0.75, "frames": []}, "frame count"),
    (seq(["standing"] * 21), "frame count"),
    (seq(["standing", "falling"]), "unknown posture"),
    ({"aspect": 0.75, "frames": [{"t": 1.0, "persons": [{"id": "P1", "posture": "standing", "x": 0.5, "y": 0.5}] * 2}]}, "duplicate"),
])
def test_malformed_probes_never_confirm(probe, detail):
    d = decide(probe, CAND)
    assert d["verdict"] == "insufficient" and d["reason"] == "invalid_probe" and detail in d["detail"]


def test_fixtures_rebuild_identically():
    """Fixtures come from labels.json + XML + video PTS; rebuild them when the sources are present."""
    if not all((HERE.parents[1] / "data/raw" / c["video"]).exists() for c in LABELS.values()):
        pytest.skip("source videos not present")
    import build_fixtures
    for name, case in LABELS.items():
        assert build_fixtures.build(name, case) == FX[name], name
