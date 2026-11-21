"""The real-clip site builder (scripts/make_real_site.py). No API calls; one test runs ffmpeg.

    python -m pytest tests/test_real_site.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fakecctv.media import probe  # noqa: E402
from make_real_site import make_sequence, sequence_offsets, site_config  # noqa: E402


def test_sequence_offsets():
    assert sequence_offsets([6.5, 11.0, 7.0], gap_s=10) == [0.0, 16.5, 37.5]


def test_sequence_offsets_with_lead_in():
    """Each offset is where that clip's own first frame lands: after its lead-in."""
    assert sequence_offsets([6.5, 11.0, 7.0], gap_s=10, lead_s=30) == [30.0, 76.5, 127.5]


def test_make_sequence_matches_its_offsets(tmp_path):
    clips = []
    for name, size, dur in (("a", "320x240", 1.5), ("b", "160x90", 2.0)):
        p = tmp_path / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"testsrc=size={size}:rate=10:duration={dur}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(p)], check=True)
        clips.append(p)
    out = tmp_path / "seq.mp4"
    offsets = make_sequence(clips, out, gap_s=1.0, lead_s=2.0)
    assert offsets == pytest.approx([2.0, 6.5])
    info = probe(out)
    assert info["duration"] == pytest.approx(2 + 1.5 + 1 + 2 + 2.0 + 1, abs=0.1)
    assert (info["width"], info["height"]) == (320, 240)


def test_site_config_has_7_cameras_and_17_labels():
    cauca = [30.0, 80.0, 130.0, 180.0, 230.0, 280.0]
    g421 = [30.0, 132.0]
    cfg = site_config(cauca, g421)
    cams = {c["id"]: c for c in cfg["cameras"]}
    assert list(cams) == [f"CAM-0{i}" for i in range(1, 8)]
    labels = [(c["id"], lab) for c in cfg["cameras"] for lab in c.get("labels", [])]
    assert len(labels) == 17
    assert all(lab["type"] != "none" for _, lab in labels)
    lookalikes = sorted((cid, lab["start"]) for cid, lab in labels   # context look-alikes, not visual ones
                        if not lab["real"] and lab["type"].startswith("after_hours"))
    assert lookalikes == [("CAM-01", 259.0), ("CAM-03", 0.0)]
    assert [lab["real"] for lab in cams["CAM-01"]["labels"]] == [True, True, False]
    assert "roster" in cams["CAM-03"]["labels"][0]["note"]
    # sequence labels shift by where their clip's first frame lands
    fall_forward, kneel = cams["CAM-04"]["labels"][:2]
    assert (fall_forward["start"], fall_forward["end"], fall_forward["real"]) == (36.0, 39.5, True)
    assert (kneel["start"], kneel["real"]) == (82.0, False)
    assert [lab["start"] for lab in cams["CAM-06"]["labels"]] == [55.0, 157.5]
    assert cfg["site"]["start"] == "2018-03-11T13:50:00" and cfg["site"]["duration_s"] == 840
    assert cams["CAM-02"]["neighbors"] == ["CAM-01", "CAM-03"]
    assert cams["CAM-07"]["doors"] == ["Stairwell door"]
