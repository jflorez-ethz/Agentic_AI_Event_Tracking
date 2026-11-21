"""Turn labels.csv into one test clip per labelled window: clips/testset/*.mp4 + testset.csv.

- Files up to MAX_LEN seconds are used as they are (CAUCAFall clips, the MEVA cuts).
- Longer files (the 5-minute MEVA recordings) are cut around each window: PRE seconds before
  the event and POST seconds after, at most MAX_LEN seconds. "none" windows are cut exactly.
- Label times in testset.csv are relative to the test clip.
Standard library + ffmpeg only, so it runs without the venv:
    python3 scripts/build_testset.py
"""
from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "labels.csv"
OUT_DIR = ROOT / "clips" / "testset"
OUT_CSV = ROOT / "testset.csv"
PRE, POST, MAX_LEN = 20.0, 10.0, 90.0


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def short_name(path: Path) -> str:
    cam = re.search(r"\.(G\d+)", path.name)
    return cam.group(1) if cam else path.stem.replace("S1", "")


def main() -> None:
    rows = list(csv.DictReader(open(LABELS, newline="", encoding="utf-8")))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_rows = []
    for i, r in enumerate(rows, 1):
        src = ROOT / r["file"]
        dur = duration(src)
        start, end = float(r["start_s"]), float(r["end_s"])
        if dur <= MAX_LEN:
            clip, offset, clip_dur = src, 0.0, dur
        else:
            if r["type"] == "none":
                a, b = start, end
            else:
                a, b = max(0.0, start - PRE), min(dur, end + POST)
                b = min(b, a + MAX_LEN)
            offset, clip_dur = a, round(b - a, 2)
            clip = OUT_DIR / f"T{i:02d}_{short_name(src)}_{a:g}-{b:g}.mp4"
            if not clip.exists():
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a}", "-i", str(src), "-t", f"{clip_dur}",
                                "-an", "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)], check=True)
            clip_dur = round(duration(clip), 2)
        out_rows.append({
            "id": f"T{i:02d}_{short_name(src)}_{r['type']}_{'real' if r['real'] == 'true' else 'look' if r['type'] != 'none' else 'none'}",
            "clip": str(clip.relative_to(ROOT)), "duration_s": round(clip_dur, 2),
            "type": r["type"], "real": r["real"],
            "start_s": round(max(0.0, start - offset), 1), "end_s": round(min(clip_dur, end - offset), 1),
            "source_file": r["file"], "source_offset_s": offset, "note": r["note"],
        })
        print(f"{out_rows[-1]['id']:<45} {clip_dur:6.1f} s  label {out_rows[-1]['start_s']}-{out_rows[-1]['end_s']}")
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    total = sum(r["duration_s"] for r in out_rows)
    print(f"\n{len(out_rows)} test clips, {total:.0f} s of video in total -> {OUT_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
