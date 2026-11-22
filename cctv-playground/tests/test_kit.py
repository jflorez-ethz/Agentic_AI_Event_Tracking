"""End-to-end checks on a tiny two-camera site built from generated clips (about 20 s to run).

    pytest -q
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cctv_playground.clock import ReplayClock  # noqa: E402
from cctv_playground.context import SiteContext  # noqa: E402
from cctv_playground.media import probe  # noqa: E402
from cctv_playground.recorder import NotYetAvailable, Recorder  # noqa: E402
from cctv_playground.site import load_site, parse_site_time  # noqa: E402
from cctv_playground.tools import AgentTools  # noqa: E402


def test_index_places_clips_and_labels(site_dir):
    site = load_site(site_dir / "site" / "index.json")
    assert [c.id for c in site.cameras] == ["CAM-A", "CAM-B"]
    a = {l.camera_id: l for l in site.labels}
    assert a["CAM-A"].start == datetime(2026, 1, 10, 2, 0, 10)  # placed at 5 s, label at 5 s of the clip
    assert a["CAM-B"].start == datetime(2026, 1, 10, 2, 0, 12)
    assert abs(probe(site.cameras[0].path)["duration"] - 30) < 0.5  # padded to the whole window


def test_meva_files_line_up_by_name(tmp_path):
    for name in ("2018-03-07.16-50-00.16-55-00.school.G336.r13.avi", "2018-03-07.16-50-06.16-55-06.school.G328.r13.avi"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=5:d=10",
                        "-c:v", "mpeg4", str(tmp_path / name)], check=True)
    (tmp_path / "site.yaml").write_text(textwrap.dedent("""
        site: {name: MEVA test, start: "2018-03-07T16:50:00", duration_s: 20, fps: 5, size: [320, 180]}
        cameras:
          - {id: CAM-1, zone: School front, source: 2018-03-07.16-50-00.16-55-00.school.G336.r13.avi, align: meva_filename}
          - {id: CAM-2, zone: School side, source: 2018-03-07.16-50-06.16-55-06.school.G328.r13.avi, align: meva_filename}
    """))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py"), str(tmp_path / "site.yaml")],
                   check=True, capture_output=True)
    import json
    cams = json.loads((tmp_path / "site" / "index.json").read_text())["cameras"]
    assert [c["source_on_site"][0] for c in cams] == ["2018-03-07T16:50:00", "2018-03-07T16:50:06"]


def test_clock_times_around_midnight():
    start, end = datetime(2026, 1, 10, 1, 50), datetime(2026, 1, 10, 2, 20)
    assert parse_site_time("22:00", start, end) == datetime(2026, 1, 9, 22, 0)
    assert parse_site_time("02:10", start, end) == datetime(2026, 1, 10, 2, 10)


def test_clock_shared_between_processes(tmp_path):
    start, end = datetime(2026, 1, 10, 2, 0), datetime(2026, 1, 10, 3, 0)
    screen = ReplayClock(start, end, tmp_path / "clock.json")
    runner = ReplayClock(start, end, tmp_path / "clock.json")
    screen.jump(start + timedelta(minutes=10))
    assert runner.now() == start + timedelta(minutes=10)
    screen.set_speed(20)
    screen.play()
    time.sleep(0.3)
    assert runner.now() > start + timedelta(minutes=10, seconds=4)
    runner.pause()
    frozen = screen.now()
    time.sleep(0.2)
    assert screen.now() == frozen


def test_recorder_refuses_the_future(site_dir, tmp_path):
    site = load_site(site_dir / "site" / "index.json")
    clock = ReplayClock(site.start, site.end)
    clock.jump(site.start + timedelta(seconds=10))
    rec = Recorder(site, clock, tmp_path)
    with pytest.raises(NotYetAvailable):
        rec.cut_clip("CAM-A", site.start, site.start + timedelta(seconds=15))
    clip = rec.cut_clip("CAM-A", site.start + timedelta(seconds=2), site.start + timedelta(seconds=8))
    assert abs(probe(clip)["duration"] - 6) < 0.6
    assert rec.frame("CAM-B", clock.now()) is not None


def test_tools_report_errors_and_keep_a_trace(site_dir, tmp_path):
    site = load_site(site_dir / "site" / "index.json")
    clock = ReplayClock(site.start, site.end)
    clock.jump(site.start + timedelta(seconds=10))
    tools = AgentTools(Recorder(site, clock, tmp_path), SiteContext(site, clock))
    assert "error" in tools.get_clip("CAM-A", "02:00:00", "02:00:20")
    assert "error" in tools.access_log("02:00:00", "02:00:20")
    assert tools.access_log("02:00:00", "02:00:09")["rows"][0]["badge"] == "B-1"
    assert tools.roster("02:00:25")["rows"]  # plans can be read ahead
    assert "error" in tools.get_clip("CAM-Z", "02:00:00", "02:00:05")
    assert [s["ok"] for s in tools.trace] == [False, False, True, True, False]


def test_evaluate_scores_the_stub(site_dir):
    import evaluate
    result = evaluate.run(str(site_dir / "site" / "index.json"), delay_s=2)
    verdicts = {r["event"]: r["verdict"] for r in result["events"]}
    assert verdicts == {"CAM-A-1": "dismiss", "CAM-B-1": "escalate"}
    assert result["summary"]["missed_critical_events"] == 0
    assert result["summary"]["alerts_reduction_pct"] == 50.0


def _two_label_index(tmp_path) -> Path:
    """An index with no footage: an unattended object at 02:00:00 and a person at 02:00:05."""
    import json
    cam = {"zone": "Z", "file": "none.mp4", "start": "2026-01-10T02:00:00", "duration_s": 120,
           "fps": 5, "width": 320, "height": 180}
    index = {"name": "Delays", "start": "2026-01-10T02:00:00", "duration_s": 120, "context": {},
             "cameras": [{"id": "CAM-A", **cam}, {"id": "CAM-B", **cam}],
             "labels": [
                 {"id": "CAM-A-1", "camera_id": "CAM-A", "type": "unattended_object",
                  "start": "2026-01-10T02:00:00", "end": "2026-01-10T02:01:00", "real": True},
                 {"id": "CAM-B-1", "camera_id": "CAM-B", "type": "after_hours_person",
                  "start": "2026-01-10T02:00:05", "end": "2026-01-10T02:00:20", "real": True}]}
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index))
    return path


def test_detector_waits_longer_for_unattended_objects(tmp_path):
    from cctv_playground.detector import OracleDetector
    site = load_site(_two_label_index(tmp_path))
    det = OracleDetector(site)
    t0 = site.start
    assert det.delay_for("unattended_object") == timedelta(seconds=30)
    assert det.delay_for("after_hours_person") == timedelta(seconds=10)
    assert det.poll(t0 + timedelta(seconds=14)) == []
    assert [c["candidate_id"] for c in det.poll(t0 + timedelta(seconds=15))] == ["CAM-B-1"]
    assert det.poll(t0 + timedelta(seconds=29)) == []
    fired = det.poll(t0 + timedelta(seconds=30))
    assert [c["candidate_id"] for c in fired] == ["CAM-A-1"]
    assert fired[0]["detected_at"] == "2026-01-10T02:00:30"
    # both due at once: detection order, not start order
    both = OracleDetector(site).poll(t0 + timedelta(seconds=60))
    assert [c["candidate_id"] for c in both] == ["CAM-B-1", "CAM-A-1"]


def test_evaluate_creates_each_alert_at_its_detection_time(tmp_path):
    """The object starts first but fires last: the person must not wait for it."""
    import evaluate

    def no_footage(candidate, tools, open_alerts):
        return {"verdict": "escalate", "priority": "high", "reason": "test", "evidence": [], "linked_to": None}

    result = evaluate.run(str(_two_label_index(tmp_path)), triage_fn=no_footage)
    tta = {r["event"]: r["time_to_alert_s"] for r in result["events"]}
    assert tta == {"CAM-A-1": 30.0, "CAM-B-1": 10.0}
