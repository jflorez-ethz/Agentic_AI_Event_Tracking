#!/usr/bin/env python3
"""Generate six simple placeholder clips so the kit runs before any dataset is downloaded.

    python scripts/make_placeholder_clips.py

Each clip is a flat drawing of one camera view with coloured blocks moving through it:
a vehicle at the gate, people in the car park and at the loading dock, someone climbing
the fence, someone falling in a warehouse aisle, and a pallet left in front of an exit.
The times match the labels in site.yaml. Replace them with real clips when you have them.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cctv_playground.media import find_font, font_option, require_ffmpeg, run  # noqa: E402

W, H, FPS = 640, 360, 10

# Each scene: background, static boxes (x, y, w, h, colour), caption, and moving actors.
# Actor: (w, h, colour, x expression, y expression, start s, end s); t is seconds into the clip.
SCENES = {
    "gate": dict(duration=480, bg="0x2e3a40", caption="Main gate", static=[
        (0, 230, 640, 70, "0x55595c"), (280, 120, 12, 110, "0x9aa3a8"), (420, 120, 12, 110, "0x9aa3a8"),
    ], actors=[
        (96, 42, "0xd9d9d9", "-96+(t-270)*9", "232", 270, 330),
    ]),
    "carpark": dict(duration=480, bg="0x33393d", caption="Car park", static=[
        (60, 250, 90, 45, "0x5b6b7a"), (180, 250, 90, 45, "0x7a5b5b"), (470, 250, 90, 45, "0x5b7a63"),
        (560, 90, 50, 120, "0x4a4f53"),
    ], actors=[
        (16, 42, "0xe2b45a", "120+(t-290)*10", "200", 290, 330),
    ]),
    "dock": dict(duration=600, bg="0x2f3437", caption="Loading dock", static=[
        (40, 80, 160, 140, "0x4b5257"), (240, 80, 160, 140, "0x4b5257"), (440, 80, 160, 140, "0x4b5257"),
        (0, 220, 640, 8, "0xc9a227"),
    ], actors=[
        (16, 42, "0xe2b45a", "600-(t-305)*6", "250", 305, 390),
    ]),
    "fence": dict(duration=600, bg="0x26302a", caption="Fence line", static=[
        (0, 140, 640, 6, "0x9aa3a8"), (0, 175, 640, 4, "0x9aa3a8"),
        (100, 140, 6, 160, "0x9aa3a8"), (300, 140, 6, 160, "0x9aa3a8"), (500, 140, 6, 160, "0x9aa3a8"),
    ], actors=[
        (16, 42, "0xe2b45a", "330", "250-(t-260)*4", 260, 300),
    ]),
    "aisle": dict(duration=600, bg="0x34383b", caption="Warehouse aisle", static=[
        (40, 60, 120, 260, "0x5a4b3c"), (480, 60, 120, 260, "0x5a4b3c"),
    ], actors=[
        (16, 42, "0xe2b45a", "200+(t-300)*5", "240", 300, 320),
        (42, 16, "0xe2b45a", "296", "268", 320, 600),
    ]),
    "exit": dict(duration=900, bg="0x30353a", caption="Emergency exit corridor", static=[
        (270, 70, 100, 170, "0x2f7d4f"), (0, 240, 640, 4, "0x6b7075"),
    ], actors=[
        (110, 70, "0x8a5a2b", "265", "200", 420, 900),
    ]),
}


def make(name: str, scene: dict, out_dir: Path, font: str) -> Path:
    out = out_dir / f"{name}.mp4"
    d = scene["duration"]
    inputs = ["-f", "lavfi", "-i", f"color=c={scene['bg']}:s={W}x{H}:r={FPS}:d={d}"]
    for (w, h, colour, *_rest) in scene["actors"]:
        inputs += ["-f", "lavfi", "-i", f"color=c={colour}:s={w}x{h}:r={FPS}:d={d}"]
    boxes = ",".join(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={c}:t=fill" for x, y, w, h, c in scene["static"])
    caption = (f"drawtext={font}fontsize=14:fontcolor=white@0.6:x=10:y=h-24:"
               f"text='PLACEHOLDER  {scene['caption']}  (replace with a real clip)'")
    chain = f"[0:v]{boxes},{caption}[s0]"
    last = "s0"
    for i, (_w, _h, _c, xe, ye, a, b) in enumerate(scene["actors"], start=1):
        chain += f";[{last}][{i}:v]overlay=x='{xe}':y='{ye}':enable='between(t,{a},{b})'[s{i}]"
        last = f"s{i}"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", chain, "-map", f"[{last}]",
         "-t", str(d), "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p", str(out)])
    return out


def main() -> None:
    require_ffmpeg()
    out_dir = ROOT / "clips" / "placeholder"
    out_dir.mkdir(parents=True, exist_ok=True)
    font = font_option(find_font())
    for name, scene in SCENES.items():
        path = make(name, scene, out_dir, font)
        print(f"  {path.relative_to(ROOT)}  ({scene['duration'] // 60} min)")
    print("Placeholder clips ready. Next: python scripts/build_site.py site.yaml")


if __name__ == "__main__":
    main()
