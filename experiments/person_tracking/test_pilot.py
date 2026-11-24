import pilot
from detections import ANNOTATIONS


def box(x):
    return (x, 0.0, x + 10.0, 20.0)


def test_idf1_and_switches():
    truth = {"g": {0: box(0), 5: box(1), 10: box(2), 15: box(3)}}
    perfect = {1: {0: box(0), 5: box(1), 10: box(2), 15: box(3)}}
    metrics, _ = pilot.evaluate(truth, perfect, [0, 5, 10, 15])
    assert metrics["idf1"] == 1.0 and metrics["id_switches"] == 0
    split = {1: {0: box(0), 5: box(1)}, 2: {10: box(2), 15: box(3)}}
    metrics, _ = pilot.evaluate(truth, split, [0, 5, 10, 15])
    assert metrics["idf1"] == 0.5 and metrics["id_switches"] == 1 and metrics["per_truth_track"]["g"]["numbers"] == 2


def test_stitching_joins_a_short_break_at_the_same_place_only():
    times = [i / 25 for i in range(200)]
    tracks = {1: {0: box(0), 5: box(1)}, 2: {30: box(3), 35: box(4)}, 3: {40: box(200), 45: box(201)}}
    merged = pilot.stitch(tracks, times, tau_s=2.0, base_px=20.0)
    assert set(merged[1]) == {0, 5, 30, 35} and 3 in merged  # far away: not joined
    assert pilot.stitch(tracks, times, tau_s=0.0, base_px=20.0) == tracks


def test_static_tracks_are_dropped_and_labels_follow_first_appearance():
    tracks = {7: {0: box(0), 5: box(0)}, 8: {10: box(0), 15: box(30)}, 9: {5: box(50), 20: box(90)}}
    kept = pilot.drop_static(tracks)
    assert set(kept) == {8, 9}
    assert pilot.label(kept) == {9: "Person A", 8: "Person B"}


def test_owners_from_xml():
    truth, bag = pilot.ground_truth(ANNOTATIONS / "lbpugt.xml")
    owner = pilot.owners(truth, bag)
    assert (owner["placed_by"], owner["picked_by"]) == ("2", "2")
