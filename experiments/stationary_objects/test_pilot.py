import pilot
from videos import ANNOTATIONS, RAW


def test_ground_truth_events():
    times = pilot.pts_times(str(RAW / "LeftBag_PickedUp.mpg"))
    events, persons = pilot.truth(ANNOTATIONS / "lbpugt.xml", times)
    assert [(e["type"], round(e["t"], 2), e["xy"]) for e in events] == [
        ("placed", 20.36, (219, 34)), ("removed", 40.88, (215, 34))]
    assert persons[600]  # person boxes come from the non-object tracks


def test_matching_respects_type_time_and_position():
    events = [{"type": "placed", "t": 20.0, "xy": (100, 100)}, {"type": "present_at_end", "t": None, "xy": (50, 50)}]
    candidates = [{"type": "placed", "t": 21.5, "xy": (110, 105)},      # within 2 s and 20 px
                  {"type": "placed", "t": 25.0, "xy": (100, 100)},      # too late: false alarm
                  {"type": "removed", "t": 20.0, "xy": (100, 100)},     # wrong type: false alarm
                  {"type": "present_at_end", "t": 34.0, "xy": (60, 60)}]
    found, false = pilot.match(candidates, events)
    assert [e["found"] for e in found] == [True, True] and found[0]["time_error_s"] == 1.5
    assert len(false) == 2
