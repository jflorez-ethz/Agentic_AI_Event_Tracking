"""person_on_floor facts and doubt signals (floor_check.py): labelled cases, signals one by one, noise, budgets. Offline."""
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
NOBODY_DOWN = sorted(n for n, fx in FIXTURES.items() if fx["expected"]["seen"] != "on_floor")
CLEAR_REAL = ["fall_true", "wiggle_true", "fight_true"]
INTERPRETATION = re.compile(r"chut|tomb|fall|fell|brusqu|progressi|sudden|gradual|collaps|accident", re.I)
S = 1_000_000


def replay(fx, transcript=None, *, standing_followups=False):
    """ask() answering from a recorded transcript; an unrecorded call fails like a provider error, or, with
    standing_followups, a follow-up shows everyone standing where they were last seen (the truth when nobody is down)."""
    calls = iter(transcript or fx["transcript"])
    last = {}

    def ask(times_us, phase):
        call = next(calls, None)
        if call is None or call["times_us"] != list(times_us) or call["phase"] != phase:
            if standing_followups and phase == "floor_followup":
                frames = [{"t_us": t, "display_index": -1, "frame_id": f"follow-{t}",
                           "persons": [{**p, "posture": "standing"} for p in last.values()]} for t in times_us]
                return f"follow-{times_us[0]}", frames
            raise RuntimeError("no recorded answer for this call")
        for frame in call["frames"]:
            last.update({p["id"]: p for p in frame["persons"]})
        return call["inspection_id"], copy.deepcopy(call["frames"])
    return ask


def run(fx, transcript=None, **kw):
    candidate = f"cand-{fx['case']}"
    (incident,) = check([(candidate, fx["anchor_us"])], replay(fx, transcript, **kw), duration_us=fx["duration_us"],
                        aspect=fx["aspect"], frame_size=tuple(fx["frame_size"]),
                        claimed=set() if fx["first_look"] == "suspected" else {candidate})
    return incident


def summary(incident, expected):
    got = {"seen": incident["seen"]}
    if "arrival_observed" in expected:
        got["arrival_observed"] = incident["arrival"]["observed"]
    if "via" in expected:
        got["via"] = incident["arrival"].get("via")
    if "floor_postures" in expected:
        got["floor_postures"] = [s["posture"] for s in incident["floor_postures"]]
    if "outcome" in expected:
        got["outcome"] = incident["outcome"]["kind"]
    return got




def codes(incident):
    return [x["code"] for x in incident["doubt_signals"]]

# ---------- frozen rules ----------

def test_rules_are_the_approved_ones():
    assert RULES["version"] == 4 and RULES["statuses"] == ["look_closely", "no_doubt_signal"]
    assert "verified_rule" not in RULES  # no threshold decides "facts verified" any more
    D = RULES["doubt_signals"]
    assert (D["few_floor_frames"]["min_frames"], D["short_floor"]["min_s"], D["small_person"]["max_height_px"],
            D["image_edge"]["max_px"], D["moving_on_floor"]["max_displacement"]) == (4, 2.0, 30, 8, 0.10)
    assert "no_floor_seen" in D and "after seeing" in D["no_floor_seen"]
    assert "kneeling" not in RULES["on_floor"] and set(RULES["on_floor"]) == {"sitting_on_floor", "lying_on_floor"}
    assert RULES["followup"]["max_per_incident"] == 3 and RULES["max_inspections_per_video"] == 6
    assert len(floor_check.probe_times(10 * S, 60 * S)) == 20


def test_the_probe_question_is_neutral():
    text = floor_check.prompt()
    assert not INTERPRETATION.search(text) and "floor" in text  # 'floor' only names the postures
    for word in [*RULES["vocabulary"], "w and h", "seat_nearby"]:
        assert word in text


# ---------- labelled cases (transcripts recorded from labels.json + CAVIAR XML) ----------

@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_known_case_facts(name):
    fx = FIXTURES[name]
    incident = run(fx)
    assert incident == fx["incidents"][0]  # the recorded run is reproduced exactly
    assert summary(incident, fx["expected"]) == fx["expected"]


def test_criterion_on_the_labelled_cases():
    """floor_rules.json criterion: every known false alert is Look closely, at most 1 of the 3 clear real falls.
    no_floor_seen was added after seeing these cases (v4): this re-checks, it does not validate."""
    assert all(run(FIXTURES[n])["status"] == "look_closely" for n in NOBODY_DOWN) and len(NOBODY_DOWN) == 7
    assert sum(run(FIXTURES[n])["status"] == "look_closely" for n in CLEAR_REAL) <= 1


def test_every_case_goes_to_the_guard():
    for fx in FIXTURES.values():
        incident = run(fx)
        assert floor_check.alerting([incident]) == [incident] and incident["status"] in RULES["statuses"]


def test_slump_false_is_look_closely_with_what_was_seen():
    """Held-out Rest_SlumpOnFloor 2.52-3.04 s: nobody is on the floor; the guard sees why to doubt it."""
    incident = run(FIXTURES["slump_false"])
    assert codes(incident) == ["disagreement", "no_floor_seen"] and incident["status"] == "look_closely"
    assert "debout tout du long" in facts_lines(incident, "fr")[0]


def test_suspicion_with_nobody_on_the_floor_is_marked():
    """Browse1: the first look only suspected it and the close check sees nobody on the floor (the v3 gap)."""
    incident = run(FIXTURES["browse1_edge"])
    assert incident["first_look"] == "suspected" and codes(incident) == ["no_floor_seen"]


def test_measured_facts_of_the_real_cases():
    fight = run(FIXTURES["fight_true"])
    assert fight["arrival"] == {"observed": True, "upright_us": 12_799_700, "seconds": 0.24, "via": []}
    assert fight["outcome"]["kind"] == "stood_up" and fight["outcome"]["via"] == ["kneeling", "bending"]
    fall = run(FIXTURES["fall_true"])
    assert fall["arrival"]["seconds"] == 1.24 and fall["arrival"]["via"] == ["bending", "kneeling"]
    assert fall["floor_seconds"] >= 8.0 and fall["followup_still_on_floor"]
    assert "status" not in str(facts_lines(fall, "en")).lower() and fall["doubt_signals"] == []


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_no_interpretation_words(name):
    incident = run(FIXTURES[name])
    for lang in ("fr", "en"):
        for line in facts_lines(incident, lang) + [floor_check.signal_text(x, lang) for x in incident["doubt_signals"]]:
            assert not INTERPRETATION.search(line), line
    assert not INTERPRETATION.search(render_markdown([incident]))
    assert "vérifi" not in render_markdown([incident]).replace("non vérifié", "")


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
def test_isolated_wrong_floor_labels_are_always_look_closely(k):
    for name in NOBODY_DOWN:
        fx = FIXTURES[name]
        for combo in itertools.combinations(slots(fx), k):
            for label in RULES["on_floor"]:
                incident = run(fx, noisy(fx, [(*s, label) for s in combo]), standing_followups=True)
                assert incident["status"] == "look_closely", (name, combo, label)


def test_short_runs_of_wrong_floor_labels_are_always_look_closely():
    for name in NOBODY_DOWN:
        fx = FIXTURES[name]
        focal = "P" + LABELS[name]["focal"]
        frames = len(fx["transcript"][0]["frames"])
        for length in range(1, 6):
            for start in range(0, frames - length + 1):
                changes = [(0, f, focal, "lying_on_floor") for f in range(start, start + length)]
                assert run(fx, noisy(fx, changes), standing_followups=True)["status"] == "look_closely", (name, start, length)


@pytest.mark.parametrize("p", [0.05, 0.10, 0.20])
def test_random_label_noise_when_nobody_is_down_is_always_look_closely(p):
    rng = random.Random(4321)
    for _ in range(120):
        for name in NOBODY_DOWN:
            fx = FIXTURES[name]
            changes = [(*s, rng.choice(RULES["vocabulary"])) for s in slots(fx) if rng.random() < p]
            assert run(fx, noisy(fx, changes), standing_followups=True)["status"] == "look_closely", (name, changes)


@pytest.mark.parametrize("name", CLEAR_REAL)
@pytest.mark.parametrize("label", ["bending", "kneeling", "sitting_on_seat"])
def test_real_cases_keep_their_facts_with_one_wrong_label(name, label):
    """One wrong label never hides the person: still on the floor. Inside the run the time on the floor stays within
    a second; on the last close-check frame it stops the follow-up (a known limit: the time on the floor is then
    shorter). It may add a signal (changing posture, a seat): that only asks the guard to look closely."""
    fx = FIXTURES[name]
    clean = run(fx)
    focal = "P" + LABELS[name]["focal"]
    frames = fx["transcript"][0]["frames"]
    for f in range(len(frames)):
        if any(p["id"] == focal for p in frames[f]["persons"]):
            incident = run(fx, noisy(fx, [(0, f, focal, label)]))
            assert incident["seen"] == "on_floor", (f, label)
            if f < len(frames) - 1:
                assert abs(incident["floor_seconds"] - clean["floor_seconds"]) <= 1.0, (f, label)
            assert set(codes(incident)) <= {"posture_flicker", "seat_nearby", "arrival_not_seen", "few_floor_frames"}, (f, label)


# ---------- signal by signal, on synthetic sequences ----------

def seq(labels, *, t0=8.0, step=0.42, moves=0.0, source="probe", x=0.5, y=0.5, box=None):
    return [(round((t0 + i * step) * S), label, None if label == "not_visible" else min(1.0, x + moves * i), y, source,
             box or {}) for i, label in enumerate(labels)]


ANCHOR = 9 * S
FLOOR = ["standing"] * 3 + ["sitting_on_floor"] + ["lying_on_floor"] * 8


def facts(sequence, anchor=ANCHOR, **kw):
    return describe(sequence, anchor, aspect=0.75, video_end_us=60 * S, **kw)


def signals(sequence, *, first_look="reported", frame_size=(384, 288), anchor=ANCHOR, frames=(), **kw):
    incident = {**facts(sequence, anchor, **kw), "anchor_us": anchor, "frames": list(frames)}
    return floor_check.mark(incident, first_look=first_look, frame_size=frame_size, aspect=0.75)


def test_clear_sequence_has_no_doubt_signal():
    r = signals(seq(FLOOR, box={"w": 0.1, "h": 0.2, "seat_nearby": False}))
    assert r["seen"] == "on_floor" and r["arrival"]["observed"] and codes(r) == [] and r["status"] == "no_doubt_signal"


def test_disagreement_both_ways_and_no_floor_seen():
    assert codes(signals(seq(["standing"] * 12))) == ["disagreement", "no_floor_seen"]
    assert codes(signals(seq(["standing"] * 12), first_look="suspected")) == ["no_floor_seen"]
    r = signals(seq(FLOOR), first_look="suspected")
    assert codes(r) == ["disagreement"] and r["doubt_signals"][0]["value"] == "suspected_someone_on_floor"


def test_kneeling_or_a_seat_after_an_on_the_floor_report_is_look_closely_with_what_was_seen():
    r = signals(seq(["standing"] * 3 + ["kneeling"] * 12))
    assert r["seen"] == "kneeling" and r["status"] == "look_closely"
    lines = facts_lines(r, "fr")
    assert "à genoux, personne au sol" in lines[0] and lines[1].startswith("Ce que l'inspection fine a vu : debout")
    seat = signals(seq(["standing"] * 3 + ["sitting_on_seat"] * 12))
    assert codes(seat) == ["disagreement", "no_floor_seen", "seat_nearby"]
    assert "assise sur un siège 00:09.26–00:13.88" in facts_lines(seat, "fr")[1]


def test_few_frames_and_short_time_on_the_floor():
    r = signals(seq(["standing"] * 3 + ["lying_on_floor"] * 3 + ["standing"] * 6))
    assert codes(r) == ["few_floor_frames", "short_floor"] and r["doubt_signals"][0]["value"] == 3
    # Still on the floor when the observation ends: the time is a minimum, not a short stay.
    assert "short_floor" not in codes(signals(seq(["standing"] * 3 + ["lying_on_floor"] * 4)))


def test_arrival_not_seen():
    r = signals(seq(["lying_on_floor"] * 12))
    assert codes(r) == ["arrival_not_seen"] and r["doubt_signals"][0]["value"] == "already_on_floor"


def test_small_person_and_image_edge_from_the_approximate_box():
    small = signals(seq(FLOOR, box={"w": 0.05, "h": 0.08}))  # 0.08 x 288 = 23 px
    assert codes(small) == ["small_person"] and small["doubt_signals"][0]["value"] == 23
    edge = signals(seq(FLOOR, x=0.97, box={"w": 0.06, "h": 0.2}))
    assert codes(edge) == ["image_edge"] and edge["doubt_signals"][0]["value"] == 0
    assert codes(signals(seq(FLOOR, box={"w": 0.05, "h": 0.08}), frame_size=None)) == []  # no size, no signal


def test_moving_on_the_floor():
    r = signals(seq(FLOOR, moves=0.03))
    assert codes(r) == ["moving_on_floor"] and r["doubt_signals"][0]["value"] > 0.10


def test_seat_next_to_a_person_on_the_floor():
    r = signals(seq(FLOOR, box={"w": 0.1, "h": 0.2, "seat_nearby": True}))
    assert codes(r) == ["seat_nearby"] and r["doubt_signals"][0]["value"] == round(9.26 * S)


def test_changing_posture():
    r = signals(seq(["standing"] * 3 + ["lying_on_floor"] * 4 + ["sitting_on_seat"] + ["lying_on_floor"] * 4))
    assert "posture_flicker" in codes(r) and "seat_nearby" in codes(r)
    bent = signals(seq(["standing"] * 3 + ["lying_on_floor"] * 4 + ["kneeling"] * 2 + ["lying_on_floor"] * 4))
    assert codes(bent) == ["posture_flicker"]


def test_identity_uncertain_in_a_followup():
    probe = seq(["standing"] * 3 + ["lying_on_floor"] * 9)
    later = seq(["lying_on_floor"] * 3, t0=14.0, step=1.0, source="followup")
    crowd = [{"t_us": t, "persons": [{"id": "A", "posture": p, "x": 0.5, "y": 0.5}, {"id": "B", "posture": "standing", "x": 0.55, "y": 0.5}]}
             for t, p, *_ in later]
    r = signals(probe + later, frames=crowd)
    assert codes(r) == ["identity_uncertain"] and r["doubt_signals"][0]["value"] == 14 * S


def test_far_in_time_from_the_report():
    r = signals(seq(FLOOR), anchor=30 * S)
    assert r["seen"] == "on_floor_not_near_report" and "première image au sol" in facts_lines(r, "fr")[-1]


def test_slow_arrival_is_described_not_refused():
    r = signals(seq(["standing"] * 3 + ["kneeling"] * 6 + ["sitting_on_floor"] * 8), anchor=12 * S)
    assert r["seen"] == "on_floor" and r["arrival"]["seconds"] > 2.5 and r["arrival"]["via"] == ["kneeling"] and codes(r) == []


def test_outcomes():
    up = facts(seq(FLOOR + ["kneeling", "standing"]))
    assert up["outcome"]["kind"] == "stood_up" and up["outcome"]["via"] == ["kneeling"]
    end = describe(seq(FLOOR), ANCHOR, aspect=0.75, video_end_us=seq(FLOOR)[-1][0] + 500_000)
    assert end["outcome"]["kind"] == "on_floor_at_end"
    stopped = facts(seq(FLOOR), followup_stopped=True)
    assert stopped["outcome"]["kind"] == "followup_stopped" and "suivi arrêté" in facts_lines(stopped, "fr")[-1]


def test_look_closely_cards_come_first():
    calm = {**signals(seq(FLOOR)), "anchor_us": 5 * S}
    doubt = {**signals(seq(["lying_on_floor"] * 12)), "anchor_us": 50 * S}
    assert floor_check.order([calm, doubt]) == [doubt, calm]
    text = render_markdown([calm, doubt])
    assert text.index("à regarder de près") < text.index("aucun signal de doute mesuré")
    assert "cela ne veut pas dire que c'est vrai" in text


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
    assert i["seen"] == "on_floor" and i["outcome"]["kind"] == "stood_up" and 40 * S <= i["outcome"]["at_us"] < 42 * S
    assert i["status"] == "no_doubt_signal"


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
    assert [i["seen"] for i in incidents[6:]] == ["budget_exhausted"] * 2
    assert [codes(i) for i in incidents[6:]] == [["no_close_check"]] * 2
    assert all(i["status"] == "look_closely" for i in incidents)  # never dismissed


def test_failed_probe_leaves_an_alert_to_review():
    def ask(times_us, phase):
        raise RuntimeError("HTTP 503")
    (i,) = check([("o1", 9 * S)], ask, duration_us=60 * S, aspect=0.75)
    assert (i["status"], i["seen"], codes(i)) == ("look_closely", "probe_failed", ["no_close_check"])
    assert floor_check.alerting([i]) == [i] and "l'inspection fine a échoué" in floor_check.signal_text(i["doubt_signals"][0], "fr")


# ---------- the two check-in demo runs (real Gemini close-check answers, prompt floor-v1, read on load) ----------

def test_demo_runs_with_real_answers():
    """Stored before rules v3: the signals are computed on read. floor-v1 asked no box and no seat, so size, edge and
    the seat-next-to signals can only come from sitting_on_seat answers here."""
    from pydantic import TypeAdapter

    from security_augmented import guard_report
    from security_augmented.workflow import Analysis

    got = []
    for run in sorted((ROOT / "experiments").glob("demo_checkin.*/run")):
        analysis = TypeAdapter(Analysis).validate_python(json.loads((run / "analysis.json").read_text())["analysis"])
        got += [(run.parent.name.split(".")[1], i["anchor_us"] // S, i["status"], codes(i))
                for i in guard_report.floor_incidents(analysis)]
    assert sorted(got) == [
        ("Rest_FallOnFloor", 11, "look_closely", ["no_floor_seen"]),            # suspicion, kneeling at the edge
        ("Rest_FallOnFloor", 27, "no_doubt_signal", []),                        # real fall
        ("Rest_SlumpOnFloor", 4, "look_closely", ["disagreement", "no_floor_seen", "seat_nearby"]),  # walker by the armchairs
        ("Rest_SlumpOnFloor", 26, "no_doubt_signal", []),                       # real slow slump
    ]
