"""Prepare blinded source views and paired assignment captures without a live client."""
import argparse
import csv
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import TypeAdapter

from evaluate import ARCHIVE, QUESTIONS, ROOT, evaluate
from security_augmented.contracts import Interval
from security_augmented.video import _decode, ingest, sample
from security_augmented.workflow import Analysis


def paired_requests():
    requests = []
    for with_question in (False, True):
        r = evaluate("visibility", with_question, capture_assignment=requests.append)
        assert not r["submitted_images"] and not r["anchor_found"]
    a, b = requests
    stripped = deepcopy(b)
    part = stripped["contents"][0]["parts"][0]
    context = json.loads(part["text"])
    assert context["relational_task"].pop("visual_question") == QUESTIONS["visibility"]
    part["text"] = json.dumps(context, ensure_ascii=False)
    if stripped != a:
        raise ValueError("Verification requests differ beyond the task question")
    return a, b


def prepare(output):
    requests = paired_requests()
    context = json.loads(requests[0]["contents"][0]["parts"][0]["text"])
    scope = Interval(**context["relational_task"]["interval"])
    archive = TypeAdapter(Analysis).validate_python(json.loads(ARCHIVE.read_text())["analysis"])
    video = ingest(ROOT / "data/raw/Meet_WalkSplit_pts.mp4")
    if video.id != archive.video.id:
        raise ValueError("Source differs from archive")
    members = context["relational_task"]["observation_ids"]
    original = {f.display_index: f for row in archive.observations if row.observation.id in members
                for f in row.citation.frames if scope.start_us <= f.source_time_us < scope.end_us}
    # Align the reference grid to the initial scan's source clock. Two legal windows
    # span the review interval. They are never offered to Verification as choices.
    start = scope.start_us
    requests_us = list(range(((start + 249999) // 250000) * 250000, scope.end_us, 250000))
    frames = dict(original)
    chunks = []
    for offset in range(0, len(requests_us), 20):
        times = requests_us[offset:offset+20]
        interval = Interval(times[0], min(scope.end_us, times[0] + 5000000))
        inspection = sample(video, interval, times)
        chunks.append(asdict(inspection))
        for f in inspection.frames:
            if f.display_index in frames and frames[f.display_index] != f:
                raise ValueError("Canonical frame mismatch")
            frames[f.display_index] = f
    ordered = [frames[i] for i in sorted(frames)]
    pixels = _decode(video, tuple(f.display_index for f in ordered))
    output.mkdir(parents=True, exist_ok=False)
    review = output / "reviewer"
    review.mkdir()
    sheet = Image.new("RGB", (4 * video.width, ((len(ordered)+3)//4)*(video.height+24)), "white")
    draw = ImageDraw.Draw(sheet)
    rows = []
    for n, (f, rgb) in enumerate(zip(ordered, pixels, strict=True)):
        if hashlib.sha256(rgb).hexdigest() != f.rgb24_sha256 or video.frame_pts[f.display_index] != f.pts:
            raise ValueError("Source verification failed")
        key = f"V{n+1:02d}"
        x, y = n%4 * video.width, n//4 * (video.height+24)
        sheet.paste(Image.frombytes("RGB", (video.width, video.height), rgb), (x,y))
        draw.text((x+4,y+video.height+4), f"{key}   {f.source_time_us/1e6:.2f} s", fill="black")
        rows.append({"view": key, **asdict(f), "original_citation": f.display_index in original})
    sheet.save(review / "views.png")
    for name in ("reviewer-1", "reviewer-2"):
        with (review / f"{name}.csv").open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["view", "source_time_us", "visibility", "visible_cue_or_limitation"])
            writer.writerows([r["view"], r["source_time_us"], "", ""] for r in rows)
    (review / "instructions.txt").write_text(
        "Work independently. Use only views.png and your own form. Zoom to native resolution. "
        "Assess the two pedestrian silhouettes on the central atrium floor at each labeled instant. "
        "Choose distinguishable if two separate body outlines or positions can be resolved; "
        "not_distinguishable if the view shows a merged or inseparable outline; uncertain if glare, "
        "occlusion, field of view or another limitation prevents deciding. Record the visible cue. "
        "Do not assign identities or interpolate motion. Lock your form before discussing it.\n")
    manifest = {"video_id": video.id, "source_sha256": video.sha256, "interval": asdict(scope),
                "members": members, "time_base": str(video.time_base), "views": rows, "reference_windows": chunks,
                "sheet_sha256": hashlib.sha256((review/"views.png").read_bytes()).hexdigest()}
    for name, value in [("manifest",manifest), ("generic",requests[0]), ("specific",requests[1])]:
        (output / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
    (output/"assessment.csv").write_text(
        "blind_packet,selected_frame_ids,answer_and_brackets,cited_frame_ids,visibility_limit,"
        "missed_transitions,unsupported_continuity,abstention,unique_new_frames,physical_requests,latency_ms\n"
        "X,,,,,,,,,,\nY,,,,,,,,,,\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output)
