"""Shared test fixtures.

- site_dir: a tiny two-camera site built from generated clips (moved here unchanged from
  test_kit.py, so the step 5 tests can use it too).
- keep_logs_out_of_runs: every test writes the cost log and the frame cache under tmp_path,
  never to the real runs/usage.jsonl.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentlab import event_check, usage  # noqa: E402


@pytest.fixture(autouse=True)
def keep_logs_out_of_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(event_check, "FRAMES_DIR", tmp_path / "frames")


@pytest.fixture(scope="module")
def site_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("site")
    for name, colour in (("a", "blue"), ("b", "green")):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"color=c={colour}:s=320x180:r=5:d=20", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(d / f"{name}.mp4")], check=True)
    (d / "access.csv").write_text("time,door,badge,holder,result\n02:00:08,Door 1,B-1,Cleaner,granted\n")
    (d / "roster.csv").write_text("start,end,who,role,zones,note\n22:00,03:00,Cleaner,Cleaning,Offices,\n")
    (d / "procedures.md").write_text("Test procedures.\n")
    (d / "site.yaml").write_text(textwrap.dedent("""
        site: {name: Test site, start: "2026-01-10T02:00:00", duration_s: 30, fps: 5, size: [320, 180]}
        context: {access_log: access.csv, roster: roster.csv, procedures: procedures.md}
        cameras:
          - id: CAM-A
            zone: Yard
            source: a.mp4
            at_s: 5
            doors: [Door 1]
            labels: [{type: after_hours_person, start: 5, end: 10, real: false}]
          - id: CAM-B
            zone: Dock
            source: b.mp4
            at_s: 0
            labels: [{type: after_hours_person, start: 12, end: 18, real: true}]
    """))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py"), str(d / "site.yaml")],
                   check=True, capture_output=True)
    return d
