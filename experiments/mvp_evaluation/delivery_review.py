"""Recheck the two frozen runs against local footage and build review sheets."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from score import artifact_hash, citation_checks, load_run, read
from security_augmented.video import _decode, ingest

HERE = Path(__file__).resolve().parent
QUERIES = (
    "What happened between 10 and 15 seconds?",
    "What happened after the two people approached each other?",
    "Did the two people separate afterward?",
)


def review(case, output):
    if artifact_hash(case["artifact"]) != case["artifact_sha256"]:
        raise ValueError("Archived output hash mismatch")
    video = ingest(Path(case["source"]))
    if video.sha256 != case["sha256"]:
        raise ValueError("Video hash mismatch")
    analysis, stats, inspections = load_run(video, case["artifact"])
    events = sorted(analysis.timeline + analysis.unresolved, key=lambda e: e.interval.start_us)
    checks = citation_checks(video, [asdict(event) for event in events], inspections)
    if checks["invalid"]:
        raise ValueError(f"Invalid citations in {checks}")
    frames = {f.display_index: f for e in events for c in e.citations for f in c.frames}
    indices = sorted(frames)
    # First, middle and last source samples of each supported finding.
    # Preserve the rest of the citations in the manifest for inspection.
    display = set()
    for event in analysis.timeline:
        cited = sorted({f.display_index for c in event.citations for f in c.frames
                        if event.interval.start_us <= f.source_time_us < event.interval.end_us})
        if cited:
            display.update((cited[0], cited[len(cited) // 2], cited[-1]))
    ordered = sorted(display)
    sheet = Image.new("RGB", (3 * video.width, ((len(ordered) + 2) // 3) * (video.height + 24)), "white")
    draw = ImageDraw.Draw(sheet)
    for n, (i, rgb) in enumerate(zip(ordered, _decode(video, tuple(ordered)), strict=True)):
        ref = frames[i]
        if hashlib.sha256(rgb).hexdigest() != ref.rgb24_sha256:
            raise ValueError(f"Source image mismatch at {i}")
        x, y = n % 3 * video.width, n // 3 * (video.height + 24)
        sheet.paste(Image.frombytes("RGB", (video.width, video.height), rgb), (x, y))
        draw.text((x + 4, y + video.height + 3), f"{i}   {ref.source_time_us / 1e6:g} s   PTS {ref.pts}", fill="black")
    sheet.save(output / "source-samples.jpg", quality=91)
    answers = [{"question": q, **asdict(analysis.ask(q))} for q in QUERIES]
    result = {"source": case["source"], "artifact": case["artifact"],
              "source_sha256": video.sha256, "artifact_sha256": case["artifact_sha256"],
              "citation_checks": checks, "unique_frames": len(indices), "sheet_indices": ordered,
              "frames": [asdict(frames[i]) for i in indices], "answers": answers,
              "initial_observations": len(analysis.observations), "supported_events": len(analysis.timeline),
              "unresolved": len(analysis.unresolved), "archived_completion": stats["completion"]}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir()
    cases = read(HERE / "cases.json")
    for name in ("walk_split", "walk_together"):
        path = args.output / name
        path.mkdir()
        review(cases[name], path)


if __name__ == "__main__":
    main()
