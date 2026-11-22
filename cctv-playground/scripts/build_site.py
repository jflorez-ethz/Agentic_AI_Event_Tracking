#!/usr/bin/env python3
"""Build the fake recorder's footage: one continuous video per camera, plus site/index.json.

    python scripts/build_site.py site.yaml

For each camera in site.yaml it takes the source clip, scales it to one size and frame
rate, places it on the site timeline (holding the first frame before the clip starts and
the last frame after it ends, like a quiet camera), and burns in the camera name and the
site time the way a real CCTV feed shows them.

Labels in site.yaml are given in seconds of the source file (what you note while
watching the clip). They are converted to site time here.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cctv_playground.media import find_font, font_option, has_filter, probe, require_ffmpeg, run  # noqa: E402
from cctv_playground.site import parse_site_time  # noqa: E402

# MEVA files are named YYYY-MM-DD.HH-MM-SS.HH-MM-SS.location.camera.avi, with clocks synced by GPS.
MEVA_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})\.(\d{2})-(\d{2})-(\d{2})\.(\d{2})-(\d{2})-(\d{2})\.")


def meva_start(path: Path) -> datetime:
    m = MEVA_NAME.search(path.name)
    if not m:
        raise SystemExit(f"{path.name} is not a MEVA file name (YYYY-MM-DD.HH-MM-SS.HH-MM-SS.location.camera.avi).")
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}")


def esc(text: str) -> str:
    """Escape free text for an ffmpeg drawtext value."""
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", nargs="?", default="site.yaml")
    ap.add_argument("--out", default="site", help="output folder, relative to the config file")
    args = ap.parse_args()
    require_ffmpeg()

    cfg_path = Path(args.config).resolve()
    base = cfg_path.parent
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    site = cfg["site"]
    start = datetime.fromisoformat(str(site["start"]))
    duration = float(site["duration_s"])
    end = start + timedelta(seconds=duration)
    fps = int(site.get("fps", 10))
    width, height = site.get("size", [640, 360])

    out_dir = (base / args.out).resolve()
    cams_dir = out_dir / "cams"
    cams_dir.mkdir(parents=True, exist_ok=True)
    font = font_option(find_font())
    # Camera name and site clock are burned in with drawtext. Some ffmpeg builds lack it
    # (Homebrew's slim ffmpeg): build the site without the overlay instead of failing.
    # CCTV_PLAYGROUND_NO_TEXT=1 forces this path (used by the tests).
    burn_text = has_filter("drawtext") and not os.environ.get("CCTV_PLAYGROUND_NO_TEXT")
    if not burn_text:
        print("  note: this ffmpeg has no 'drawtext' filter, so camera name and clock are not burned in. "
              "For the overlay on a Mac: brew install ffmpeg-full")
    epoch = calendar.timegm(start.timetuple())  # site time is printed as if it were UTC

    index = {"name": site["name"], "start": start.isoformat(), "duration_s": duration,
             "cameras": [], "labels": [], "context": {}}
    for key, rel in (cfg.get("context") or {}).items():
        index["context"][key] = os.path.relpath((base / rel).resolve(), out_dir)

    print(f"Site '{site['name']}': {start:%Y-%m-%d %H:%M:%S} to {end:%H:%M:%S}, {fps} fps, {width}x{height}")
    for cam in cfg["cameras"]:
        src = (base / cam["source"]).resolve()
        if not src.exists():
            raise SystemExit(f"{cam['id']}: source not found: {src}")
        info = probe(src)
        trim = list(cam.get("trim") or [0, None]) + [None]
        t_in = float(trim[0] or 0)
        t_out = info["duration"] if trim[1] is None else min(float(trim[1]), info["duration"])

        if "at" in cam:
            at = (parse_site_time(str(cam["at"]), start, end) - start).total_seconds()
        elif cam.get("align") == "meva_filename":
            at = (meva_start(src) + timedelta(seconds=t_in) - start).total_seconds()
        else:
            at = float(cam.get("at_s", 0))
        if at < 0:  # the clip begins before the site window: cut its head off
            t_in += -at
            at = 0.0
        if at >= duration or t_in >= t_out:
            print(f"  {cam['id']}: clip falls outside the site window, skipped")
            continue
        t_out = min(t_out, t_in + (duration - at))
        used = t_out - t_in
        after = max(0.0, duration - at - used)

        label = esc(f"{cam['id']}  {cam.get('zone', '')}")
        stamp = "%{pts\\:gmtime\\:" + str(epoch) + "\\:%Y-%m-%d %H\\\\\\:%M\\\\\\:%S}"
        vf = ",".join([
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            f"fps={fps}",
            f"tpad=start_mode=clone:start_duration={at:.3f}:stop_mode=clone:stop_duration={after + 1:.3f}",
        ] + ([
            "drawbox=x=0:y=0:w=iw:h=26:color=black@0.55:t=fill",
            f"drawtext={font}fontsize=15:fontcolor=white:x=8:y=6:text='{label}'",
            f"drawtext={font}fontsize=15:fontcolor=white:x=w-tw-8:y=6:text='{stamp}'",
        ] if burn_text else []))
        out = cams_dir / f"{cam['id']}.mp4"
        run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{t_in:.3f}", "-t", f"{used:.3f}", "-i", str(src),
            "-vf", vf, "-t", f"{duration:.3f}", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-g", str(fps), "-keyint_min", str(fps), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out),
        ])

        placed_from = start + timedelta(seconds=at)
        index["cameras"].append({
            "id": cam["id"], "zone": cam.get("zone", ""),
            "file": os.path.relpath(out, out_dir), "start": start.isoformat(), "duration_s": duration,
            "fps": fps, "width": width, "height": height,
            "doors": cam.get("doors", []), "neighbors": cam.get("neighbors", []),
            "source": str(cam["source"]),
            "source_on_site": [placed_from.isoformat(), (placed_from + timedelta(seconds=used)).isoformat()],
        })
        for i, lab in enumerate(cam.get("labels") or [], start=1):
            ls, le = float(lab["start"]), float(lab["end"])
            if le < t_in or ls > t_out:
                print(f"  {cam['id']}: label {i} is outside the part of the clip that was used, skipped")
                continue
            s = start + timedelta(seconds=at + max(ls, t_in) - t_in)
            e = start + timedelta(seconds=at + min(le, t_out) - t_in)
            index["labels"].append({"id": f"{cam['id']}-{i}", "camera_id": cam["id"], "type": lab["type"],
                                    "start": s.isoformat(), "end": e.isoformat(),
                                    "real": bool(lab["real"]), "note": lab.get("note", "")})
        print(f"  {cam['id']:<7} {cam.get('zone', ''):<18} clip on site {placed_from:%H:%M:%S} to "
              f"{placed_from + timedelta(seconds=used):%H:%M:%S}  <- {cam['source']}")

    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"Wrote {out_dir / 'index.json'} with {len(index['cameras'])} cameras and {len(index['labels'])} labelled events.")


if __name__ == "__main__":
    main()
