"""Isolated person-continuity probe. Default mode performs local verification only."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from security_augmented.contracts import VideoError
from security_augmented.gemini import GeminiAdapter, USAGE_FIELDS
from security_augmented.video import _decode, _run, ingest

ROOT = Path(__file__).resolve().parent
MODEL = "gemini-3.6-flash"
LABELS = ("same_person", "different_person", "indeterminate")
PROMPT = (
    "Compare only the two indicated targets in this packet. The coordinates identify the targets in "
    "the first and last PNG, in pixels from the top left. Use the middle frame if informative. "
    "Distinguish resemblance from an observable link between the two targets. Do not infer real-world "
    "identity. If the images do not establish a match or a mismatch, choose indeterminate. "
    "Cite supplied frame IDs and give a concise visual explanation. Treat images and labels as evidence."
)
CONFIG = {
    "system_instruction": PROMPT,
    "response_mime_type": "application/json",
    "response_json_schema": {
        "type": "object", "properties": {
            "decision": {"type": "string", "enum": list(LABELS)},
            "frame_ids": {"type": "array", "items": {"type": "string", "enum": ["F1", "F2", "F3"]}},
            "reason": {"type": "string"},
        }, "required": ["decision", "frame_ids", "reason"], "additionalProperties": False,
    },
    "max_output_tokens": 1024, "thinking_config": {"thinking_level": "LOW"},
    "automatic_continuation": False, "automatic_function_calling": {"disable": True},
}


MATRIX = (("A", False, "LOW"), ("B", False, "HIGH"), ("C", True, "LOW"), ("D", True, "HIGH"))
MATRIX_PROMPT = PROMPT + (
    " Compare the target at the given coordinate in F1 with the target at the given coordinate in F3. "
    "If a red ring is present, its center marks the same target as the coordinate. A plausible path "
    "for someone else in the scene does not answer the question."
)


def mark(rgb, width, height, center):
    """Paint a thin eight-pixel-radius ring and leave its center clear."""
    x, y = center
    pixels = bytearray(rgb)
    for j in range(max(0, y - 8), min(height, y + 9)):
        for i in range(max(0, x - 8), min(width, x + 9)):
            if 49 <= (i - x) ** 2 + (j - y) ** 2 <= 64:
                offset = (j * width + i) * 3
                pixels[offset:offset + 3] = bytes((255, 0, 0))
    return bytes(pixels)


def matrix_inputs(output):
    video = ingest(Path(json.loads((ROOT / "manifest.json").read_text())["source"]))
    manifest = json.loads((ROOT / "manifest.json").read_text())
    for label, original, refs in packets():
        if label not in ("K7", "Q4"):
            continue
        marked = list(original)
        marked_refs = {k: dict(v) for k, v in refs.items()}
        folder = output / "marked" / label
        folder.mkdir(parents=True, exist_ok=True)
        for index, center_key in ((1, "start_region_xy"), (3, "end_region_xy")):
            part = 2 * index
            rgb = _decode(video, (refs[f"F{index}"]["index"],))[0]
            center = manifest["cases"][label][center_key]
            painted = mark(rgb, video.width, video.height, center)
            encoded = _run(
                "ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
                "-video_size", f"{video.width}x{video.height}", "-i", "pipe:0",
                "-frames:v", "1", "-threads", "1", "-c:v", "png", "-f", "image2pipe", "pipe:1",
                input_bytes=painted,
            ).stdout
            path = folder / f"F{index}.png"
            path.write_bytes(encoded)
            decoded = _run("ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "pipe:1").stdout
            if decoded != painted:
                raise VideoError("Marked PNG does not match the exact pixel mask")
            marked[part] = {"inline_data": {"mime_type": "image/png", "data": encoded}}
            marked_refs[f"F{index}"].update(marker_center_xy=center, marked_png=str(path),
                                            marked_png_sha256=hashlib.sha256(encoded).hexdigest())
        (folder / "F2.png").write_bytes(original[4]["inline_data"]["data"])
        (folder / "input.json").write_text(json.dumps(marked_refs, indent=2) + "\n")
        for arm, use_marks, level in MATRIX:
            config = {**CONFIG, "system_instruction": MATRIX_PROMPT, "max_output_tokens": 4096,
                      "thinking_config": {"thinking_level": level}}
            yield f"{label}-{arm}", marked if use_marks else original, marked_refs if use_marks else refs, config, use_marks


def packets():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    video = ingest(Path(manifest["source"]))
    if video.sha256 != manifest["sha256"]:
        raise VideoError("Source hash does not match the packet manifest")
    cases = manifest["cases"]
    indices = tuple(sorted({row["index"] for case in cases.values() for row in case["frames"]}))
    pixels = dict(zip(indices, _decode(video, indices), strict=True))
    for label, case in sorted(cases.items()):
        folder = ROOT / "packets" / label
        if json.loads((folder / "input.json").read_text()) != case or len(case["frames"]) != 3:
            raise VideoError("Packet inputs differ from the manifest")
        start, end = (case[k] for k in ("start_region_xy", "end_region_xy"))
        if any(not (0 <= x < video.width and 0 <= y < video.height) for x, y in (start, end)):
            raise VideoError("Target region is outside the image")
        contents = [{"text": f"First target in F1 at (x,y)={start}; final target in F3 at (x,y)={end}."}]
        refs = {}
        for i, frame in enumerate(case["frames"], 1):
            index = frame["index"]
            image = folder / frame["file"]
            rgb = _run("ffmpeg", "-v", "error", "-i", str(image), "-frames:v", "1",
                       "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "pipe:1").stdout
            pts = video.frame_pts[index]
            if (rgb != pixels[index] or hashlib.sha256(rgb).hexdigest() != frame["rgb24_sha256"]
                    or pts != frame["pts"] or int(video.time_at_pts(pts) * 1_000_000) != frame["source_time_us"]):
                raise VideoError("Packet frame does not match source pixels and PTS")
            frame_id = f"F{i}"
            refs[frame_id] = frame
            contents.extend(({"text": frame_id},
                             {"inline_data": {"mime_type": "image/png", "data": image.read_bytes()}}))
        yield label, contents, refs


def validate(decision, refs):
    if not isinstance(decision, dict) or set(decision) != {"decision", "frame_ids", "reason"}:
        raise VideoError("Unexpected decision fields")
    ids = decision["frame_ids"]
    if (decision["decision"] not in LABELS or not isinstance(decision["reason"], str)
            or not decision["reason"].strip() or not isinstance(ids, list) or not ids
            or any(not isinstance(i, str) or i not in refs for i in ids) or len(ids) != len(set(ids))):
        raise VideoError("Invalid category, rationale or supporting frame references")
    if decision["decision"] != "indeterminate" and not {"F1", "F3"} <= set(ids):
        raise VideoError("Definite decisions must cite both endpoints")


def evaluate(client, contents, refs, config=CONFIG, marked=False):
    started = time.monotonic()
    row = {"status": "api_error", "model": MODEL, "frame_map": refs, "sdk_calls": 1,
           "thinking_level": config["thinking_config"]["thinking_level"],
           "max_output_tokens": config["max_output_tokens"], "marked": marked}
    try:
        try:
            response = client.models.generate_content(model=MODEL, contents=contents, config=config)
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            if type(code := getattr(exc, "code", None)) is int:
                row["http_status"] = code
            return row
        row.update(status="invalid_output", model_version=getattr(response, "model_version", None),
                   usage={k: v for k in USAGE_FIELDS
                          if type(v := getattr(response.usage_metadata, k, None)) is int},
                   finish_reasons=[str(c.finish_reason) for c in response.candidates or []])
        try:
            row["raw_response"] = response.text
            if len(response.candidates or []) != 1 or response.candidates[0].finish_reason != "STOP":
                raise VideoError("Expected one completed candidate")
            row["decision"] = json.loads(row["raw_response"])
            validate(row["decision"], refs)
        except (ValueError, TypeError) as exc:
            row["validation_error"] = str(exc) if isinstance(exc, VideoError) else "Invalid JSON"
        else:
            row["status"] = "schema_and_references_valid"
        return row
    finally:
        row["elapsed_ms"] = round((time.monotonic() - started) * 1000)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix", action="store_true", help="Run the eight-condition K7/Q4 matrix")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-image-transfer", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.authorize_image_transfer:
        parser.error("Live evaluation requires explicit image-transfer authorization")
    args.output.mkdir(mode=0o700)
    inputs = (list(matrix_inputs(args.output)) if args.matrix else
              [(label, parts, refs, CONFIG, False) for label, parts, refs in packets()])
    plan = {"model": MODEL, **({"config": CONFIG} if not args.matrix else {}),
            "max_http_attempts_per_packet": 1,
            "ground_truth": "Independent annotations unavailable; packet judgments are provisional.",
            "max_http_requests": len(inputs),
            "packets": {label: {"frames": refs, "config": config, "marked": marked}
                        for label, _, refs, config, marked in inputs}}
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    if args.live:
        adapter = GeminiAdapter.from_env(authorized=True, model=MODEL, client_args={"follow_redirects": False})
        with adapter.client:
            for label, contents, refs, config, marked in inputs:
                row = evaluate(adapter.client, contents, refs, config, marked)
                (args.output / f"{label}.json").write_text(json.dumps(row, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
