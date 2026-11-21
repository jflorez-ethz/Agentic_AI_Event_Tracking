#!/usr/bin/env python3
"""Write the real-clip demo site: site.real.yaml, context/real/ and two sequence clips.

    python scripts/make_real_site.py
    python scripts/build_site.py site.real.yaml --out site_real

Sunday 11 March 2018, 13:50 to 14:04, a school/logistics site that is closed all day.
CAM-01 to CAM-03 are one MEVA five-minute slot (same facility, same time, so they are each
other's neighbours). CAM-04 and CAM-06 play several short clips one after another
(sequences); CAM-05 and CAM-07 are single cut clips.

Labels come from labels.csv (seconds of each source file; `none` rows skipped). Two real
events become look-alikes here because of the site context (CONTEXT_LOOKALIKES): the roster
and the access log explain them.

A sequence holds each clip's first frame for `lead_s` before it and its last frame for
`gap_s` after it. The lead-in keeps the agent's usual first clip (20 s before first seen)
from reaching back into the previous clip; the tail keeps a fallen person on screen until
the detector fires.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fakecctv.media import probe, require_ffmpeg, run  # noqa: E402

LABELS_CSV = ROOT / "labels.csv"
SEQ_DIR = Path("clips/sequences")
LEAD_S = 30.0
GAP_S = 10.0

MEVA = "clips/meva/2018-03-11.13-50-0{}.school.{}.r13.mp4"
G336 = MEVA.format("1.13-55-00", "G336")
G328 = MEVA.format("1.13-55-01", "G328")
G330 = MEVA.format("0.13-54-59", "G330")
G331 = "clips/meva_cut/2018-03-15.15-15-00.15-20-00.bus.G331_160-230.mp4"
G326 = "clips/meva_cut/2018-03-07.16-50-01.16-55-01.admin.G326_60-110.mp4"
CAUCAFALL = [f"clips/caucafall/{n}S1.mp4" for n in
             ("FallForward", "Kneel", "FallBackwards", "Pickupobject", "FallSitting", "SitDown")]
G421 = ["clips/meva_cut/2018-03-11.11-30-01.11-35-01.school.G421_8-70.mp4",
        "clips/meva_cut/2018-03-11.11-35-01.11-40-01.school.G421_36-100.mp4"]
CAUCAFALL_SEQ = SEQ_DIR / "cam04_caucafall.mp4"
G421_SEQ = SEQ_DIR / "cam06_g421.mp4"

# (file, start_s) -> note: real activity that the site context makes expected.
CONTEXT_LOOKALIKES = {
    (G336, 259.0): "weekend guard arriving; badge at Main gate 13:54:22",
    (G330, 0.0): "cleaning contractor on the roster for the hall",
}

ACCESS_LOG = """time,door,badge,holder,result
13:41:05,Hall door,B-1107,Clean & Co staff,granted
13:54:22,Main gate,B-0412,Weekend guard,granted
"""
ROSTER = """start,end,who,role,zones,note
13:00,15:00,Clean & Co (2 staff),Cleaning contractor,Hall,Enter through the hall door
13:54,18:00,Weekend guard,Security,Drop-off loop; Main gate,Arrives by car at the start of the shift
"""
RULE_1_OLD = ("1. The site is closed from 22:00 to 06:00. A person or vehicle in the yard, at the loading dock "
              "or at the fence in those hours is expected only if")
RULE_1_NEW = "1. The site is closed all day on Sundays. A person or vehicle anywhere on site is expected only if"
RULE_2_OLD = "2. Unexpected activity after hours:"
RULE_2_NEW = "2. Unexpected activity while the site is closed:"


def sequence_offsets(durations: list[float], gap_s: float = 10.0, lead_s: float = 0.0) -> list[float]:
    """Where each clip's own first frame lands in the sequence (after its lead-in)."""
    offsets, t = [], 0.0
    for d in durations:
        offsets.append(round(t + lead_s, 3))
        t += lead_s + d + gap_s
    return offsets


def make_sequence(paths: list[Path], out: Path, gap_s: float = 10.0, lead_s: float = 0.0) -> list[float]:
    """Join clips into one video, each with its first frame held `lead_s` before it and its last
    frame held `gap_s` after it. All parts take the first clip's size and frame rate.
    Returns sequence_offsets() of the source durations, after checking the output matches them."""
    infos = [probe(p) for p in paths]
    w, h, fps = infos[0]["width"], infos[0]["height"], infos[0]["fps"]
    parts = [
        f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps:g},"
        f"tpad=start_mode=clone:start_duration={lead_s:.3f}:stop_mode=clone:stop_duration={gap_s:.3f}[v{i}]"
        for i in range(len(paths))
    ]
    graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(paths))) + \
        f"concat=n={len(paths)}:v=1:a=0[out]"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p in paths:
        cmd += ["-i", str(p)]
    run(cmd + ["-filter_complex", graph, "-map", "[out]", "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "18", "-pix_fmt", "yuv420p", str(out)])

    durations = [i["duration"] for i in infos]
    expected = sum(durations) + len(paths) * (lead_s + gap_s)
    got = probe(out)["duration"]
    if abs(got - expected) > 1.5 / fps:
        raise SystemExit(f"{out}: {got:.2f} s long, expected {expected:.2f} s; the label offsets would be wrong.")
    return sequence_offsets(durations, gap_s, lead_s)


def read_labels(path: Path = LABELS_CSV) -> dict[str, list[dict]]:
    """labels.csv by file, `none` rows skipped, context look-alikes applied."""
    by_file: dict[str, list[dict]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["type"] == "none":
                continue
            start = float(row["start_s"])
            lab = {"type": row["type"], "start": start, "end": float(row["end_s"]),
                   "real": row["real"].strip().lower() == "true", "note": row["note"]}
            if (row["file"], start) in CONTEXT_LOOKALIKES:
                lab.update(real=False, note=CONTEXT_LOOKALIKES[(row["file"], start)])
            by_file.setdefault(row["file"], []).append(lab)
    return by_file


def _labels(by_file: dict[str, list[dict]], files: list[str], offsets: list[float] | None = None) -> list[dict]:
    out = []
    for f, off in zip(files, offsets or [0.0] * len(files)):
        if f not in by_file:
            raise SystemExit(f"labels.csv has no labels for {f}.")
        for lab in by_file[f]:
            out.append({**lab, "start": round(lab["start"] + off, 3), "end": round(lab["end"] + off, 3)})
    return out


def site_config(caucafall_offsets: list[float], g421_offsets: list[float]) -> dict:
    by_file = read_labels()

    def cam(cid, zone, source, labels, *, at=None, doors=(), neighbors=()):
        c = {"id": cid, "zone": zone, "source": str(source)}
        c.update({"at": at} if at else {"align": "meva_filename"})
        c.update({k: list(v) for k, v in (("doors", doors), ("neighbors", neighbors)) if v})
        c["labels"] = labels
        return c

    return {
        "site": {"name": "Demo site (real clips)", "start": "2018-03-11T13:50:00", "duration_s": 840,
                 "fps": 10, "size": [640, 360]},
        "context": {"access_log": "context/real/access_log.csv", "roster": "context/real/roster.csv",
                    "procedures": "context/real/procedures.md"},
        "cameras": [
            cam("CAM-01", "Drop-off loop", G336, _labels(by_file, [G336]), doors=["Main gate"], neighbors=["CAM-02"]),
            cam("CAM-02", "Car park", G328, _labels(by_file, [G328]), neighbors=["CAM-01", "CAM-03"]),
            cam("CAM-03", "Hall", G330, _labels(by_file, [G330]), doors=["Hall door"], neighbors=["CAM-02"]),
            cam("CAM-04", "Warehouse aisle", CAUCAFALL_SEQ, _labels(by_file, CAUCAFALL, caucafall_offsets),
                at="13:56:00"),
            cam("CAM-05", "Waiting area", G331, _labels(by_file, [G331]), at="13:58:30"),
            cam("CAM-06", "Lobby", G421_SEQ, _labels(by_file, G421, g421_offsets), at="14:00:00"),
            cam("CAM-07", "Stairwell door", G326, _labels(by_file, [G326]), at="14:02:00", doors=["Stairwell door"]),
        ],
    }


def procedures_text(kit: Path = ROOT / "context" / "procedures.md") -> str:
    text = kit.read_text(encoding="utf-8")
    for old, new in ((RULE_1_OLD, RULE_1_NEW), (RULE_2_OLD, RULE_2_NEW)):
        if old not in text:
            raise SystemExit(f"context/procedures.md changed; cannot find: {old!r}")
        text = text.replace(old, new)
    for stale in ("22:00", "06:00", "night", "after hours"):
        if stale in text.lower():
            raise SystemExit(f"procedures for the real site still mention {stale!r}")
    return text


def main() -> None:
    require_ffmpeg()
    print("Building sequences (each clip: 30 s first-frame lead-in, clip, 10 s last-frame hold)")
    cauca = make_sequence([ROOT / p for p in CAUCAFALL], ROOT / CAUCAFALL_SEQ, GAP_S, LEAD_S)
    g421 = make_sequence([ROOT / p for p in G421], ROOT / G421_SEQ, GAP_S, LEAD_S)
    print(f"  {CAUCAFALL_SEQ}: clips start at {cauca} s")
    print(f"  {G421_SEQ}: clips start at {g421} s")

    cfg = site_config(cauca, g421)
    header = ("# Generated by scripts/make_real_site.py from labels.csv. Edit that script, not this file.\n"
              "# Build: python scripts/build_site.py site.real.yaml --out site_real\n\n")
    (ROOT / "site.real.yaml").write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True,
                                                                  width=120), encoding="utf-8")
    ctx = ROOT / "context" / "real"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "access_log.csv").write_text(ACCESS_LOG, encoding="utf-8")
    (ctx / "roster.csv").write_text(ROSTER, encoding="utf-8")
    (ctx / "procedures.md").write_text(procedures_text(), encoding="utf-8")
    n = sum(len(c["labels"]) for c in cfg["cameras"])
    print(f"Wrote site.real.yaml ({len(cfg['cameras'])} cameras, {n} labels) and context/real/.")


if __name__ == "__main__":
    main()
