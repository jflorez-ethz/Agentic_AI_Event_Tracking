"""Reproduce the bounded LeftBag case and its original-source frame mapping."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from security_augmented.contracts import Interval
from security_augmented.video import extract_clip, ingest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for the local excerpt and mapping")
    args = parser.parse_args()
    original = ingest(Path("data/raw/LeftBag.mpg"))
    inspection, pixels = extract_clip(original, Interval(30_000_000, 55_000_000))
    args.output.mkdir()
    (args.output / "left-bag.mkv").write_bytes(pixels)
    (args.output / "original-frame-map.json").write_text(json.dumps({
        "original_source_sha256": original.sha256, "inspection": asdict(inspection),
    }, indent=2) + "\n")
    print(inspection.artifact_sha256, inspection.clip_duration_us)


if __name__ == "__main__":
    main()
