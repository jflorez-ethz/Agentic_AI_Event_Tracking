"""Prepare and authorize one matched, frame-only perception request per arm."""
import argparse
import base64
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
from unittest.mock import patch

from probe import MODEL, PROMPT, SOURCE, run_media, save
from security_augmented.agents import RoleHTTPBudget
from security_augmented.contracts import Interval, VideoError
from security_augmented.gemini import MAX_INLINE_BYTES, GeminiAdapter
from security_augmented.observation import FrameSequenceInput, ObservationRequest
from security_augmented.video import _decode, ingest, sample

WINDOW = Interval(5_000_000, 20_000_000)
STEPS = (500, 250)


def sha(data):
    return hashlib.sha256(data).hexdigest()


# Categories as frozen in the prepared arms; later production taxonomy additions must not change them.
FROZEN_LABELS = ("object_placed", "object_removed", "person_enters_area", "person_appeared",
                 "person_moved", "object_appeared", "object_disappeared")


def build(video, step_ms):
    inspection = sample(video, WINDOW, list(range(WINDOW.start_us, WINDOW.end_us, step_ms * 1000)))
    if inspection.status != "complete" or len(inspection.frames) != 15_000 // step_ms:
        raise VideoError("Unexpected frame count, repeated selection or missed sample")
    pixels = _decode(video, tuple(f.display_index for f in inspection.frames))
    media = FrameSequenceInput(inspection, video.width, video.height, pixels)
    return GeminiAdapter(model=MODEL, single_request=True).prepare(
        ObservationRequest(media, (*FROZEN_LABELS, "insufficient_evidence"), PROMPT),
    )


def png_bytes(prepared):
    return [part["inline_data"]["data"] for part in prepared.contents[0]["parts"] if "inline_data" in part]


def fingerprint_sdk_body(prepared):
    """Measure JSON actually emitted by the installed SDK via a local mock."""
    import httpx
    from google import genai
    from google.genai import types

    records = []

    def capture(request):
        if request.url.path != f"/v1beta/models/{MODEL}:generateContent":
            raise VideoError("Unexpected SDK request route")
        body = json.loads(request.content)
        media = [p["inlineData"] for p in body["contents"][0]["parts"] if "inlineData" in p]
        mime_types = {part.get("mimeType", part.get("mime_type")) for part in media}
        encoded = [part["data"] for part in media]
        decoded = [base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)) for value in encoded]
        if mime_types != {"image/png"} or decoded != png_bytes(prepared):
            raise VideoError("Serialized inputs differ from the prepared PNG sequence")
        config = body["generationConfig"]
        if (config["maxOutputTokens"] != 8192 or config["thinkingConfig"]["thinking_level"] != "HIGH"
                or config["responseJsonSchema"] != prepared.config["response_json_schema"]):
            raise VideoError("Serialized generation configuration differs")
        records.append({"sdk_body_bytes": len(request.content), "sdk_body_sha256": sha(request.content),
                        "image_count": len(media)})
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": '{"observations": []}'}]},
        }]})

    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        sdk = genai.Client(api_key="local-mock-only", vertexai=False, http_options=types.HttpOptions(
            api_version="v1beta", timeout=90_000, retry_options=types.HttpRetryOptions(attempts=1),
            client_args={"transport": httpx.MockTransport(capture), "follow_redirects": False},
        ))
    with sdk:
        sdk.models.generate_content(model=MODEL, contents=prepared.contents,
                                    config={**prepared.config, "automatic_continuation": False})
    record, = records
    if record["sdk_body_bytes"] > MAX_INLINE_BYTES:
        raise VideoError("Serialized SDK request exceeds the project's inline ceiling")
    return record


def prepare(output):
    video = ingest(SOURCE)
    arms = {step: build(video, step) for step in STEPS}
    sparse, dense = arms.values()
    if (sparse.media_map["frames"] != dense.media_map["frames"][::2]
            or sparse.media_map["requested_times_us"] != dense.media_map["requested_times_us"][::2]
            or png_bytes(sparse) != png_bytes(dense)[::2]
            or sparse.config != dense.config):
        raise VideoError("The paired inputs are not nested samples with identical settings")
    fingerprints = {step: fingerprint_sdk_body(arm) for step, arm in arms.items()}
    output.mkdir(mode=0o700)
    for step, prepared in arms.items():
        wire = fingerprints[step]
        folder = output / f"step-{step}"
        folder.mkdir()
        files = []
        images = png_bytes(prepared)
        for i, png in enumerate(images, 1):
            name = f"F{i:02}.png"
            (folder / name).write_bytes(png)
            files.append({"file": name, "label": f"F{i}", "sha256": sha(png), "bytes": len(png)})
        save(folder, "input.json", {
            "source": str(SOURCE), "source_sha256": video.sha256, "frame_step_ms": step, "model": MODEL,
            "sdk_version": version("google-genai"), "inspection": prepared.media_map,
            "config": prepared.config, "text_parts": [p["text"] for p in prepared.contents[0]["parts"] if "text" in p],
            "pngs": files, "raw_png_bytes": sum(f["bytes"] for f in files), **wire,
        })


def run(plan, step, output):
    folder = plan / f"step-{step}"
    manifest = json.loads((folder / "input.json").read_text())
    video = ingest(SOURCE)
    if video.sha256 != manifest["source_sha256"] or version("google-genai") != manifest["sdk_version"]:
        raise VideoError("Source or SDK differs from the frozen comparison")
    prepared = build(video, step)
    if (json.loads(json.dumps(prepared.media_map)) != manifest["inspection"]
            or [sha(p) for p in png_bytes(prepared)] != [f["sha256"] for f in manifest["pngs"]]
            or any(sha((folder / f["file"]).read_bytes()) != f["sha256"] for f in manifest["pngs"])
            or fingerprint_sdk_body(prepared)["sdk_body_sha256"] != manifest["sdk_body_sha256"]):
        raise VideoError("Reconstructed request differs from the frozen arm")
    transport = RoleHTTPBudget(1)
    transport.attempts = []

    def before_send(request):
        if (request.url.path != f"/v1beta/models/{MODEL}:generateContent"
                or sha(request.content) != manifest["sdk_body_sha256"]):
            raise VideoError("Outbound request differs from the frozen arm")
        transport.before_send(request)

    output.mkdir(mode=0o700)
    save(output, "input.json", manifest)
    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        adapter = GeminiAdapter.from_env(authorized=True, model=MODEL, single_request=True, client_args={
            "follow_redirects": False,
            "event_hooks": {"request": [before_send], "response": [transport.after_response]},
        })
    with adapter.client:
        result = run_media(adapter, prepared)
    result.update(transport_attempts=transport.attempts, physical_http_requests=transport.sent)
    save(output, "result.json", result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    plans = modes.add_parser("prepare", help="Extract both arms locally without external calls")
    plans.add_argument("--output", required=True, type=Path)
    live = modes.add_parser("run", help="Send one authorized arm")
    live.add_argument("--prepared", required=True, type=Path)
    live.add_argument("--frame-step-ms", required=True, type=int, choices=STEPS)
    live.add_argument("--output", required=True, type=Path)
    live.add_argument("--authorize-footage-transfer", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "prepare":
        prepare(args.output)
    else:
        if not args.authorize_footage_transfer:
            parser.error("Explicit authorization for footage transfer is required")
        run(args.prepared, args.frame_step_ms, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
