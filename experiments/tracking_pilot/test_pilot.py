from pathlib import Path

import pilot

XML = Path(__file__).resolve().parents[2] / "data/annotations/lbpugt.xml"


def test_ground_truth_tracks_and_kinds():
    truth, kinds = pilot.xml_tracks(XML)
    assert set(truth) == {"0", "1", "2", "4"}
    assert kinds["4"] == "object" and kinds["2"] == "person"
    assert min(truth["4"]) == 503 and max(truth["4"]) == 1015  # bag from 20.36 s to 40.84 s (PTS)


def test_evaluation_counts_coverage_numbers_and_switch_times():
    truth = {"a": {0: (0, 0, 10, 10), 1: (0, 0, 10, 10), 2: (0, 0, 10, 10), 3: (0, 0, 10, 10)}}
    predicted = {0: [{"box": (0, 0, 10, 10), "track": 7}], 1: [{"box": (1, 1, 10, 10), "track": 7}],
                 2: [{"box": (0, 0, 10, 10), "track": 9}], 3: [{"box": (50, 50, 60, 60), "track": 9}]}
    row = pilot.evaluate(truth, {"a": "person"}, predicted, {0, 1, 2, 3}, times=[0.0, 0.2, 0.4, 0.6])["a"]
    assert row["coverage"] == 0.75 and row["distinct_track_numbers"] == 2 and row["identity_switches"] == 1
    assert row["switch_seconds"] == [0.4] and row["dominant_number_share"] == 0.5
    assert pilot.iou((0, 0, 10, 10), (5, 0, 15, 10)) == 1 / 3
