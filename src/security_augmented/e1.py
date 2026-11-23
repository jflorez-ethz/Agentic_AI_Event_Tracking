"""Prepare or run the controlled LeftBag frame-versus-clip pilot."""

import argparse
from datetime import date, datetime, timezone
from dataclasses import asdict
import hashlib
import tempfile
import json
from pathlib import Path

from .contracts import Interval, VideoError
from .gemini import (
    DEFAULT_MODEL, PROMPT_VERSION, GeminiAdapter, GeminiFailure, PreparedGemini, validate_webm,
)
from .observation import (
    ClipInput, FrameReference, FrameSequenceInput, ObservationRequest, resolve_clip_reference,
)
from .video import extract_clip, ingest, sample, validate_reference

WINDOWS = (
    ("window-a", Interval(36_000_000, 40_000_000)),
    ("window-b", Interval(37_400_000, 38_200_000)),
    ("window-c", Interval(44_000_000, 48_000_000)),
)
FPS = 2.0
CATEGORIES = ("object_placed", "object_removed", "insufficient_evidence")
PROMPT = (
    "Describe visible object placement or removal. Use object_placed only when a "
    "visible object is set down and remains in view, and object_removed only when "
    "a visible object is picked up and moves away from its previous location. "
    "Use insufficient_evidence when a potentially relevant action is visible "
    "but the available evidence cannot establish placement or removal. "
    "Report each distinct observation once."
)


def _json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _archive_request(path, prepared, model):
    parts = []
    for index, part in enumerate(prepared.contents[0]["parts"]):
        if "inline_data" not in part:
            parts.append(part)
            continue
        blob = part["inline_data"]
        data = blob["data"]
        extension = ".png" if blob["mime_type"] == "image/png" else ".webm"
        name = f"part-{index}{extension}"
        (path / name).write_bytes(data)
        parts.append({**part, "inline_data": {
            "mime_type": blob["mime_type"], "path": name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }})
    _json(path / "request.json", {
        "model": model, "contents": [{"role": "user", "parts": parts}],
        "config": prepared.config, "inspection": prepared.media_map,
    })


def _replay_manifest(request, result):
    inspection = request.media.inspection
    manifest = []
    for observation in result.observations:
        reference = observation.evidence
        if isinstance(reference, FrameReference):
            ids = set(reference.frame_ids)
            frames = tuple(frame for frame in inspection.frames if frame.id in ids)
        else:
            frames = resolve_clip_reference(inspection, reference)
        manifest.append({
            "observation_id": observation.id, "source_video_id": inspection.video_id,
            "inspection_id": inspection.id, "resolved_source_frames": [asdict(f) for f in frames],
        })
    return manifest


def _estimated_cost(metadata, observed_date):
    if metadata.model_id != DEFAULT_MODEL:
        return None
    usage = dict(metadata.usage)
    if not {"prompt_token_count", "candidates_token_count"} <= usage.keys():
        return None
    input_rate, output_rate = (0.75, 3.75) if observed_date <= date(2026, 12, 31) else (1.50, 7.50)
    estimated = (
        usage["prompt_token_count"] * input_rate
        + (usage["candidates_token_count"] + usage.get("thoughts_token_count", 0)) * output_rate
    ) / 1_000_000
    return {
        "estimated_usd": estimated, "basis": "published standard paid rates; no cache discount",
        "input_usd_per_million": input_rate, "output_usd_per_million": output_rate,
    }


def _run_arm(adapter, path, request, repetitions, *, require_observation=False):
    try:
        prepared = adapter.prepare(request)
        _archive_request(path, prepared, adapter.model)
    except VideoError as exc:
        _json(path / "preparation-error.json", {"error": str(exc)})
        return {"status": "preparation_failed"}
    return _run_prepared(adapter, path, prepared, repetitions, require_observation=require_observation)


def _run_prepared(
    adapter, path, prepared, repetitions, *, require_observation=False, assess_placement=False,
):
    request = prepared.request
    media = request.media
    frames = media.inspection.frames
    is_clip = isinstance(media, ClipInput)
    coverage = {
        "request_image_parts": None if is_clip else len(frames),
        "encoded_clip_frames": len(frames) if is_clip else None,
        "requested_clip_fps": (
            prepared.contents[0]["parts"][-1]["video_metadata"]["fps"] if is_clip else None
        ),
        "provider_processed_video_frames": None,
        "first_source_us": frames[0].source.source_time_us if is_clip else frames[0].source_time_us,
        "last_source_us": frames[-1].source.source_time_us if is_clip else frames[-1].source_time_us,
    }
    attempts = []
    for index in range(1, repetitions + 1):
        started = datetime.now(timezone.utc)
        try:
            result = adapter.infer_prepared(prepared)
        except GeminiFailure as exc:
            record = {
                "status": "failed", "failure_stage": exc.stage, "error": str(exc),
                "metadata": asdict(exc.metadata),
                "raw_response": exc.raw_response, "response_details": exc.response_details,
                "cost": _estimated_cost(exc.metadata, started.date()),
            }
        else:
            record = {
                "status": "failed" if require_observation and not result.observations else "success",
                **asdict(result),
                "replay": _replay_manifest(request, result),
                "cost": _estimated_cost(result.metadata, started.date()),
            }
        if require_observation and record["status"] == "failed" and "error" not in record:
            record["error"] = "Smoke response contained no evidence-linked observation"
        if assess_placement:
            if record["status"] != "success":
                assessment = "unscored"
            elif any(obs.category == "object_placed" for obs in result.observations):
                assessment = "placement_reported_review_required"
            else:
                assessment = "missed_positive"
            record["placement_assessment"] = assessment
        record["started_utc"] = started.isoformat()
        _json(path / f"attempt-{index}.json", record)
        attempts.append(record["status"])
    return {"status": "attempted" if repetitions else "prepared_offline", **coverage, "attempts": attempts}


def run_pilot(adapter, source, output, *, repetitions=0):
    video = ingest(source)
    output.mkdir(mode=0o700)
    _json(output / "source.json", asdict(video))
    summary = {"model": adapter.model, "live": bool(repetitions), "windows": {}}
    for name, interval in WINDOWS:
        window_path = output / name
        window_path.mkdir()
        arms = summary["windows"][name] = {}
        try:
            clip = ClipInput(*extract_clip(video, interval))
            origin = clip.inspection.frames[0].source.source_time_us
            times = list(range(origin, interval.end_us, round(1_000_000 / FPS)))
        except VideoError as exc:
            _json(window_path / "extraction-error.json", {"error": str(exc)})
            arms["extraction"] = {"status": "preparation_failed"}
            continue
        for mode, media in (("frames", None), ("clip", clip)):
            path = window_path / mode
            path.mkdir()
            try:
                if media is None:
                    inspection = sample(video, interval, times)
                    pixels = tuple(validate_reference(video, inspection, f.id) for f in inspection.frames)
                    media = FrameSequenceInput(inspection, video.width, video.height, pixels)
                request = ObservationRequest(media, CATEGORIES, PROMPT)
                arms[mode] = _run_arm(adapter, path, request, repetitions)
            except VideoError as exc:
                _json(path / "extraction-error.json", {"error": str(exc)})
                arms[mode] = {"status": "preparation_failed"}
    _json(output / "summary.json", summary)
    return summary


def run_smoke(adapter, source, output, *, repetitions=0):
    video = ingest(source)
    interval = WINDOWS[1][1]
    inspection = sample(video, interval, [interval.start_us, interval.start_us + 500_000])
    if len(inspection.frames) != 2:
        raise VideoError("Smoke case requires two distinct frames")
    pixels = tuple(validate_reference(video, inspection, f.id) for f in inspection.frames)
    media = FrameSequenceInput(inspection, video.width, video.height, pixels)
    request = ObservationRequest(
        media, ("visible_activity",),
        "Describe one visible action or posture in the images as visible_activity. Cite its frame labels.",
    )
    output.mkdir(mode=0o700)
    _json(output / "source.json", asdict(video))
    status = _run_arm(adapter, output, request, repetitions, require_observation=True)
    summary = {"model": adapter.model, "live": bool(repetitions), "windows": {"smoke": {"frames": status}}}
    _json(output / "summary.json", summary)
    return summary


def _load_clip_retry(directory, source):
    """Rehydrate one archived clip request without regenerating the submitted media."""
    try:
        archived = json.loads((directory / "request.json").read_text())
        original = json.loads((directory / "attempt-1.json").read_text())
        content, = archived["contents"]
        prompt, part = content["parts"]
        blob = part["inline_data"]
        if (
            content["role"] != "user" or set(prompt) != {"text"} or blob["path"] != "part-1.webm"
            or blob["mime_type"] != "video/webm" or part["video_metadata"] != {"fps": 2.0}
            or original["metadata"]["prompt_version"] != PROMPT_VERSION
            or original["metadata"]["model_id"] != archived["model"]
        ):
            raise VideoError("Archive differs from the supported E1 clip request")
        config = archived["config"]
        schema = config["response_json_schema"]
        categories = tuple(schema["properties"]["observations"]["items"]["properties"]["category"]["enum"])
        media_map = archived["inspection"]
        requested = Interval(**media_map["requested_interval"])
        if media_map["modality"] != "clip" or requested != WINDOWS[0][1]:
            raise VideoError("Retry archive must describe the Window A clip")
    except VideoError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise VideoError("Invalid E1 request archive") from exc

    payload = (directory / blob["path"]).read_bytes()
    if len(payload) != blob["bytes"] or hashlib.sha256(payload).hexdigest() != blob["sha256"]:
        raise VideoError("Archived WebM hash or size does not match the request")

    inspection, artifact = extract_clip(ingest(source), requested)
    # JSON-normalize tuples before comparing with the original manifest.
    if json.loads(json.dumps(asdict(inspection))) != {
        key: value for key, value in media_map.items() if key != "ffmpeg_version"
    }:
        raise VideoError("Archived clip inspection differs from replayed source evidence")
    with tempfile.TemporaryDirectory() as temp:
        clip = Path(temp) / "submitted.webm"
        clip.write_bytes(payload)
        validate_webm(clip, inspection)

    request = ObservationRequest(ClipInput(inspection, artifact), categories, prompt["text"])
    contents = [{**content, "parts": [prompt, {
        **part, "inline_data": {"mime_type": blob["mime_type"], "data": payload},
    }]}]
    return archived["model"], PreparedGemini(request, contents, config, media_map, single_request=True)


def run_clip_retry(adapter, prepared, output, *, live=False):
    output.mkdir(mode=0o700)
    _archive_request(output, prepared, adapter.model)
    result = _run_prepared(adapter, output, prepared, int(live), assess_placement=True)
    _json(output / "summary.json", {"model": adapter.model, "live": live, **result})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/raw/LeftBag.mpg"))
    parser.add_argument("--output", type=Path, required=True, help="New local directory for media and logs")
    parser.add_argument("--model", help="Override GEMINI_MODEL")
    parser.add_argument("--smoke", action="store_true", help="Prepare or send just the two-frame smoke request")
    parser.add_argument("--live", action="store_true", help="Perform Gemini inference")
    parser.add_argument("--authorize-footage-transfer", action="store_true")
    parser.add_argument("--repeat", type=int, choices=(1, 2, 3))
    parser.add_argument("--retry-clip", type=Path, help="Replay the archived Window A clip once")

    args = parser.parse_args()
    try:
        if args.retry_clip:
            if args.smoke or args.model or args.repeat is not None:
                parser.error("--retry-clip uses the archived model and a single attempt")
            if args.output.resolve().is_relative_to(args.retry_clip.resolve().parent.parent):
                parser.error("Retry output must be outside the original experiment directory")
            model, prepared = _load_clip_retry(args.retry_clip, args.source)
            adapter = (
                GeminiAdapter.from_env(authorized=args.authorize_footage_transfer, model=model)
                if args.live else GeminiAdapter(model=model)
            )
            result = run_clip_retry(adapter, prepared, args.output, live=args.live)
            print(json.dumps(result, indent=2))
            return int("failed" in result["attempts"])
        adapter = (
            GeminiAdapter.from_env(authorized=args.authorize_footage_transfer, model=args.model, clip_fps=FPS)
            if args.live else GeminiAdapter(model=args.model, clip_fps=FPS)
        )
        if args.smoke:
            summary = run_smoke(adapter, args.source, args.output, repetitions=int(args.live))
        else:
            summary = run_pilot(adapter, args.source, args.output, repetitions=(args.repeat or 2) if args.live else 0)
    except (VideoError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(summary, indent=2))
    failed = any(
        arm["status"] == "preparation_failed" or "failed" in arm.get("attempts", ())
        for window in summary["windows"].values() for arm in window.values()
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
