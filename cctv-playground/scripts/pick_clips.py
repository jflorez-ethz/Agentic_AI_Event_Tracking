#!/usr/bin/env python3
"""Shortlist clips instead of watching thousands of videos.

UCA (sentences with start and end times over UCF-Crime videos):

    python scripts/pick_clips.py uca --json path/to/UCA_Test.json path/to/UCA_Val.json \
        --categories Burglary Stealing Vandalism Arson Explosion Normal \
        --keywords night door gate fence climb truck warehouse parking \
        --out shortlist_uca.csv

    Ranks every annotated moment by how many keywords its sentence contains, so the
    team watches the top 60 or so moments and keeps about 20.

MEVA (one facility, cameras synchronised by GPS, five-minute files named by time):

    aws s3 ls --no-sign-request --recursive s3://mevadata-public-01/ > meva_listing.txt
    python scripts/pick_clips.py meva --listing meva_listing.txt --min-cameras 4
    python scripts/pick_clips.py meva --listing meva_listing.txt --slot "2018-03-07 16:50"

    The first call lists five-minute slots recorded by many cameras at once. The second
    prints the download commands for every camera in one slot: that is your multi-camera site.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------- UCA

def _uca_records(path: Path):
    """Yield (video, start_s, end_s, sentence) from a UCA JSON file.

    Expected layout (ActivityNet-captions style):
      {"Burglary018_x264": {"duration": 92.4, "timestamps": [[1.2, 5.0], ...], "sentences": ["A man ...", ...]}, ...}
    A list of {"video", "start", "end", "sentence"} records is accepted as well."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for video, rec in data.items():
            if isinstance(rec, dict) and "timestamps" in rec and "sentences" in rec:
                for (s, e), sentence in zip(rec["timestamps"], rec["sentences"]):
                    yield video, float(s), float(e), str(sentence).strip()
            else:
                raise SystemExit(f"{path}: unexpected record for {video}: keys {list(rec)[:6]}. "
                                 "Adapt _uca_records() to this layout.")
    elif isinstance(data, list):
        for rec in data:
            video = rec.get("video") or rec.get("video_name") or rec.get("vid")
            s = rec.get("start", rec.get("start_time"))
            e = rec.get("end", rec.get("end_time"))
            sentence = rec.get("sentence") or rec.get("caption") or rec.get("description")
            if None in (video, s, e, sentence):
                raise SystemExit(f"{path}: unexpected record keys {list(rec)[:6]}. Adapt _uca_records().")
            yield video, float(s), float(e), str(sentence).strip()
    else:
        raise SystemExit(f"{path}: not a JSON object or list.")


def uca(args) -> None:
    cats = {c.lower() for c in (args.categories or [])}
    words = [w.lower() for w in (args.keywords or [])]
    rows = []
    for p in args.json:
        for video, s, e, sentence in _uca_records(Path(p)):
            m = re.match(r"([A-Za-z]+)", video)
            category = m.group(1) if m else ""
            if cats and category.lower() not in cats:
                continue
            text = sentence.lower()
            hits = [w for w in words if re.search(rf"\b{re.escape(w)}", text)]
            if words and not hits:
                continue
            rows.append({"video": video, "category": category, "start_s": round(s, 1), "end_s": round(e, 1),
                         "hits": len(hits), "keywords": " ".join(hits), "sentence": sentence})
    rows.sort(key=lambda r: (-r["hits"], r["category"], r["video"], r["start_s"]))
    for r in rows[: args.top]:
        print(f"{r['hits']}  {r['video']:<28} {r['start_s']:>7.1f}-{r['end_s']:<7.1f} {r['sentence'][:90]}")
    print(f"\n{len(rows)} moments matched; showing {min(len(rows), args.top)}.")
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["video"])
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {args.out}. Add a column 'keep' while you watch, then copy the keepers into site.yaml.")

# ---------------------------------------------------------------------------- MEVA

MEVA = re.compile(r"(\d{4}-\d{2}-\d{2})\.(\d{2})-(\d{2})-(\d{2})\.(\d{2}-\d{2}-\d{2})\.([A-Za-z0-9-]+)\.(G\d+)[^/\s]*\.avi")


def meva(args) -> None:
    files = []
    for line in Path(args.listing).read_text(encoding="utf-8").splitlines():
        key = line.split()[-1] if line.strip() else ""
        m = MEVA.search(key)
        if m:
            date, hh, mm, ss, _end, location, camera = m.groups()
            slot = f"{date} {hh}:{int(mm) // 5 * 5:02d}"
            files.append({"slot": slot, "location": location, "camera": camera, "key": key})
    if not files:
        raise SystemExit("No MEVA video files found in the listing.")
    if args.location:
        files = [f for f in files if f["location"].lower() == args.location.lower()]

    by_slot = defaultdict(list)
    for f in files:
        by_slot[f["slot"]].append(f)

    if args.slot:
        chosen = by_slot.get(args.slot)
        if not chosen:
            raise SystemExit(f"No files in slot {args.slot}.")
        print(f"# {len(chosen)} cameras recorded {args.slot}. Download them with:")
        for f in sorted(chosen, key=lambda f: (f["location"], f["camera"])):
            print(f"aws s3 cp --no-sign-request s3://mevadata-public-01/{f['key']} clips/meva/")
        print("# Then add one camera per file to site.yaml with:  align: meva_filename")
        return

    slots = sorted(by_slot.items(), key=lambda kv: (-len({f['camera'] for f in kv[1]}), kv[0]))
    print(f"{'slot':<17} {'cameras':>7}  locations")
    shown = 0
    for slot, fs in slots:
        cams = {f["camera"] for f in fs}
        if len(cams) < args.min_cameras:
            continue
        locs = ", ".join(sorted({f["location"] for f in fs}))
        print(f"{slot:<17} {len(cams):>7}  {locs}")
        shown += 1
        if shown >= args.top:
            break
    print("\nPick one slot whose locations you can describe as one site, then rerun with --slot.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("uca", help="rank UCA-annotated moments by keywords")
    a.add_argument("--json", nargs="+", required=True)
    a.add_argument("--categories", nargs="*")
    a.add_argument("--keywords", nargs="*")
    a.add_argument("--top", type=int, default=60)
    a.add_argument("--out")
    b = sub.add_parser("meva", help="find five-minute slots recorded by many MEVA cameras")
    b.add_argument("--listing", required=True, help="output of: aws s3 ls --no-sign-request --recursive s3://mevadata-public-01/")
    b.add_argument("--min-cameras", type=int, default=3)
    b.add_argument("--location", help="keep one location, e.g. school, admin, bus")
    b.add_argument("--slot", help='e.g. "2018-03-07 16:50" to print download commands for that slot')
    b.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    uca(args) if args.mode == "uca" else meva(args)


if __name__ == "__main__":
    sys.exit(main())
