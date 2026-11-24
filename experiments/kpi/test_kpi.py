"""KPI checks: synthetic cases computed by hand, hand_check.md on two archived runs, XML instants."""
import json
from dataclasses import asdict
from pathlib import Path

import pytest

import kpi
from security_augmented.video import ingest

ROOT = kpi.ROOT
STRICT = kpi.RULES["matching"]["strict_categories"]
LENIENT = kpi.RULES["matching"]["lenient_categories"]


def item(cat, start, end, seed="o1"):
    return {"kind": "supported", "category": cat, "start": start, "end": end, "seed": seed, "frames": []}


def ev(cat, t):
    return {"category": cat, "t": t, "frame": 0}


# ---------- matching, by hand ----------

def test_tolerance_boundary_is_inclusive():
    assert kpi.match([item("object_placed", 10, 12)], [ev("object_placed", 14.0)], 2.0, STRICT)[0] == [(0, 0)]
    assert kpi.match([item("object_placed", 10, 12)], [ev("object_placed", 14.01)], 2.0, STRICT)[0] == []


def test_duplicate_alert_is_false_and_closest_wins():
    items = [item("person_fell", 20, 21, "a"), item("person_fell", 25, 26, "b")]
    matched, false_items, missed = kpi.match(items, [ev("person_fell", 25.5)], 2.0, STRICT)
    assert matched == [(1, 0)] and false_items == [0] and missed == []


def test_category_must_be_compatible():
    items = [item("object_appeared", 19, 20)]
    events = [ev("object_placed", 20.36)]
    assert kpi.match(items, events, 2.0, STRICT)[0] == []
    assert kpi.match(items, events, 2.0, LENIENT)[0] == [(0, 0)]


def test_one_to_one_two_events_two_alerts():
    items = [item("object_placed", 10, 11, "a"), item("object_placed", 12, 13, "b")]
    events = [ev("object_placed", 11.5), ev("object_placed", 12.2)]
    matched, false_items, missed = kpi.match(items, events, 2.0, STRICT)
    assert sorted(matched) == [(0, 0), (1, 1)] and not false_items and not missed


def synthetic_run(observed=(), scanned=30.0):
    finding = lambda cat, s, e: {"observation": {"category": cat}, "citation": {"interval": {"start_us": int(s * 1e6), "end_us": int(e * 1e6)}}}
    return {"evidence": [{"phase": "initial", "findings": [finding(*o) for o in observed]}],
            "coverage": {"initial_scan_end_us": int(scanned * 1e6)}}


def test_miss_causes():
    assert kpi.miss_cause(synthetic_run(scanned=30), ev("object_removed", 40), 2.0, STRICT) == "not_covered"
    assert kpi.miss_cause(synthetic_run(), ev("object_removed", 20), 2.0, STRICT) == "never_seen"
    seen = synthetic_run([("object_removed", 21, 22)])
    assert kpi.miss_cause(seen, ev("object_removed", 20), 2.0, STRICT) == "dismissed"


def test_time_to_alert_unknown_when_trace_and_calls_disagree():
    run = {"role_calls": [{"role": "investigation", "elapsed_ms": 1000}],
           "analysis": {"trace": [], "evidence": []}}
    assert kpi.time_to_alert(run, item("person_fell", 1, 2), 1.5) == (None, None)


def test_time_to_alert_by_hand():
    run = {"role_calls": [{"role": "investigation", "elapsed_ms": 10000}, {"role": "verification", "elapsed_ms": 5000},
                          {"role": "verification", "elapsed_ms": 7000}, {"role": "reporting", "elapsed_ms": 3000}],
           "analysis": {"trace": [
               {"actor": "investigation", "action": "decision", "observation_ids": []},
               {"actor": "verification", "action": "decision", "observation_ids": []},
               {"actor": "verification", "action": "verdict", "observation_ids": ["o1"]},
               {"actor": "verification", "action": "decision", "observation_ids": []},
               {"actor": "reporting", "action": "decision", "observation_ids": []}],
               "evidence": [{"phase": "initial", "interval": {"start_us": 0, "end_us": 10_000_000}, "inference": {"elapsed_ms": 20000}},
                            {"phase": "initial", "interval": {"start_us": 10_000_000, "end_us": 20_000_000}, "inference": {"elapsed_ms": 18000}}]}}
    # as run: 20 + 18 (all windows) + 10 + 5 (calls up to the verdict) = 53 s
    # live: (20 - 12) waiting for the window + 18 + 10 + 5 = 41 s
    assert kpi.time_to_alert(run, item("person_fell", 11, 13), 12.0) == (53.0, 41.0)


def test_cost_by_hand():
    run = {"role_calls": [{"model": "gemini-3.6-flash", "usage": {"prompt_token_count": 1_000_000, "candidates_token_count": 100_000,
                                                                   "thoughts_token_count": 100_000}}],
           "analysis": {"evidence": [{"inference": {"model_id": "gemini-3.6-flash", "usage": [["prompt_token_count", 2_000_000],
                                                                                         ["candidates_token_count", 0]]}}]}}
    c = kpi.cost(run)
    assert c["launch"]["agents"] == pytest.approx(0.75 + 0.2 * 3.75)
    assert c["standard"]["perception"] == pytest.approx(2 * 1.50)
    assert c["unpriced_calls"] == 0


# ---------- hand_check.md on two archived runs (test inputs only, never KPI rows) ----------

def archived(name):
    run = json.loads((ROOT / f"experiments/{name}/run/analysis.json").read_text())
    report = (ROOT / f"experiments/{name}/run/report.md").read_text()
    return run, report


def test_hand_check_fall():
    run, report = archived("fall_live.Q2OExt")
    events = kpi.xml_events(ROOT / "data/annotations/Rest_FallOnFloor.xml", run["analysis"]["video"])
    assert [(e["category"], e["frame"], round(e["t"], 2)) for e in events] == [("person_fell", 655, 26.44)]
    r = kpi.evaluate(run, events, 2.0, STRICT, report)
    assert len(r["found"]) == 1 and r["missed"] == [] and len(r["items"]) == 1 and r["false_items"] == []
    assert r["report_produced"] and r["lead"] == "person_fell"


def test_hand_check_picked_up():
    run, report = archived("LeftBag_PickedUp_live.kocJd7")
    events = kpi.xml_events(ROOT / "data/annotations/lbpugt.xml", run["analysis"]["video"])
    assert [(e["category"], round(e["t"], 2)) for e in events] == [("object_placed", 20.36), ("object_removed", 40.88)]
    r = kpi.evaluate(run, events, 2.0, STRICT, report)
    assert [f["event"]["category"] for f in r["found"]] == ["object_placed"]
    assert [(m["category"], m["cause"]) for m in r["missed"]] == [("object_removed", "never_seen")]
    assert len(r["items"]) == 1 and r["false_items"] == []
    assert r["valid_citations"][0] == r["valid_citations"][1] > 0


# ---------- XML instants against experiments/stationary_objects ----------

@pytest.mark.parametrize("video, xml, expected", [
    ("LeftBag.mpg", "LeftBag.xml", [("object_placed", 38.04), ("object_removed", 54.44)]),
    ("LeftBox_pts.mkv", "LeftBox.xml", [("object_placed", 23.08)]),
    ("Walk2.mpg", "wk2gt.xml", []),
])
def test_xml_events_match_stationary_pilot(video, xml, expected):
    v = asdict(ingest(ROOT / "data/raw" / video))
    events = kpi.xml_events(ROOT / "data/annotations" / xml, v)
    assert [(e["category"], round(e["t"], 2)) for e in events] == expected


# ---------- held-out mode ----------

def test_unscorable_tail_is_neither_real_nor_false():
    run = {"role_calls": [], "analysis": {
        "timeline": [], "evidence": [], "trace": [], "coverage": {"initial_scan_end_us": 52_000_000},
        "video": {"duration_us": 52_000_000},
        "review": {"alerts": [
            {"reason_code": "unclear_observation", "category": "person_fell", "observation_id": "a",
             "interval": {"start_us": 27_000_000, "end_us": 28_000_000}, "frames": []},
            {"reason_code": "unclear_observation", "category": "person_fell", "observation_id": "b",
             "interval": {"start_us": 49_000_000, "end_us": 50_000_000}, "frames": []}]}}}
    r = kpi.evaluate(run, [ev("person_fell", 27.76)], 2.0, STRICT, "", unscorable_after=47.76)
    assert len(r["found"]) == 1 and r["false_items"] == [] and len(r["unscorable_items"]) == 1
    r = kpi.evaluate(run, [ev("person_fell", 27.76)], 2.0, STRICT, "")
    assert len(r["false_items"]) == 1 and r["unscorable_items"] == []


def test_heldout_truth_is_consistent():
    truth = json.loads((kpi.HERE / "heldout_truth.json").read_text())
    assert truth["system_version"] == kpi.RULES["system_version"]
    events = [(v, e["category"], e["source"]) for v, d in truth["videos"].items() for e in d["events"]]
    assert len(events) == 5
    assert sum(1 for _, c, _ in events if c == "person_fell") == 3
    assert [s for v, _, s in events if v == "LeftBag_BehindChair.mpg"] == ["manual", "manual"]
    for d in truth["videos"].values():
        assert all(e["t"] == round(e["t"], 4) and e["frame"] >= 0 for e in d["events"])


def test_false_alerts_split_confirmed_and_review():
    rs = {"v": {"main": {"events": [], "found": [], "items": [item("person_fell", 2, 3), item("person_fell", 8, 9)],
                         "false_items": [item("person_fell", 2, 3), {**item("person_fell", 8, 9), "kind": "needs_review:unclear_observation"}],
                         "valid_citations": [0, 0], "scanned_s": 60.0},
                "cost": {"launch": {"perception": 0.1, "agents": 0.1}}}}
    t = kpi.totals(rs)
    assert (t["false_confirmed"], t["false_review"], t["false"]) == (1, 1, 2)
