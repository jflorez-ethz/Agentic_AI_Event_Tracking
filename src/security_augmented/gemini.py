"""Gemini Developer API adapter with replayable inline media."""

from dataclasses import asdict, dataclass
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import tempfile
import time

from .contracts import Interval, VideoError
from .relations import PERCEPTION_CLAIMS, perception_review
from .observation import (
    ClipInput, ClipReference, FrameReference, FrameSequenceInput, InferenceMetadata, Observation,
    ObservationRequest, ObservationResult, PostureRequest, PostureResult, validate_postures, validate_request,
    validate_result,
)
from .video import _decode, _id, _run, _version, ingest

DEFAULT_MODEL = "gemini-3.6-flash"
PROMPT_VERSION = "e1-v1"
POSTURE_PROMPT_VERSION = "floor-v2"  # v2: approximate box (w, h) and seat_nearby
ASSESSMENT_PROMPT_VERSION = "floor-assess-v1"
ADAPTER_VERSION = "1"
MAX_INLINE_BYTES = 19_000_000
USAGE_FIELDS = (
    "prompt_token_count", "candidates_token_count", "thoughts_token_count",
    "cached_content_token_count", "total_token_count",
)
TEXT_FIELDS = ("category", "description", "visibility_limits", "uncertainty")
EVIDENCE_FIELDS = ("frame_labels", "clip_interval_us")


class GeminiFailure(VideoError):
    def __init__(self, message, metadata, raw_response=None, response_details=None, *, stage="api", diagnostics=None):
        super().__init__(message)
        self.stage = stage
        self.metadata = metadata
        self.raw_response = raw_response
        self.response_details = response_details
        self.diagnostics = diagnostics


def completion_diagnostics(response):
    candidates = getattr(response, "candidates", None)
    if candidates is None:
        return {"candidate_count": None, "finish_reasons": None}
    return {
        "candidate_count": len(candidates),
        "finish_reasons": [getattr(c.finish_reason, "value", c.finish_reason) for c in candidates],
    }


@dataclass(frozen=True)
class PreparedGemini:
    request: ObservationRequest
    contents: list
    config: dict
    media_map: dict
    single_request: bool = False


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def _relation_schema(frame_count):
    integer = {"type": "integer"}
    label = {"type": "string", "enum": [f"F{i}" for i in range(1, frame_count + 1)]}
    nullable = {"type": "null"}
    mark = _object({key: {"type": "number"} for key in ("x", "y", "radius")})
    return {"anyOf": [_object({
        "claim": {"type": "string", "enum": list(PERCEPTION_CLAIMS)},
        "interval": _object({"start_us": integer, "end_us": integer}),
        "views": {"type": "array", "minItems": 1, "maxItems": frame_count, "items": _object({
            "frame_label": label,
            "marks": {"anyOf": [nullable, {"type": "array", "minItems": 2, "maxItems": 2, "items": mark}]},
        })},
        "distinct_paths": {"type": "boolean"},
        "nearby_frame_label": {"anyOf": [nullable, label]},
    }), nullable]}


def _response_schema(categories, relational_frame_count=None, possible_category=False):
    properties = {field: {"type": "string"} for field in TEXT_FIELDS}
    properties["category"]["enum"] = list(categories)
    if possible_category:
        properties["possible_category"] = {
            "type": "string", "enum": [c for c in categories if c != "insufficient_evidence"] + ["none"]}
    properties["frame_labels"] = {"type": "array", "items": {"type": "string"}}
    properties["clip_interval_us"] = {"type": "array", "items": {"type": "integer"}, "maxItems": 2}
    schema = {"type": "object", "required": ["observations"], "properties": {
        "observations": {"type": "array", "items": {
            "type": "object", "required": list(properties), "properties": properties,
        }},
    }}
    if relational_frame_count is not None:
        schema["properties"]["relation"] = _relation_schema(relational_frame_count)
    return schema


def _webm(media: ClipInput) -> bytes:
    """Encode an exact visual copy on the same clock for inline Gemini input."""
    with tempfile.TemporaryDirectory() as directory:
        original = Path(directory) / "original.mkv"
        submitted = Path(directory) / "submitted.webm"
        original.write_bytes(media.artifact)
        _run(
            "ffmpeg", "-v", "error", "-nostdin", "-xerror", "-copyts", "-i", str(original),
            "-map", "0:v:0", "-map_metadata", "-1", "-map_chapters", "-1",
            "-fps_mode", "passthrough", "-enc_time_base", "filter", "-c:v", "libvpx-vp9",
            "-lossless", "1", "-lag-in-frames", "0", "-auto-alt-ref", "0", "-threads", "1",
            "-fflags", "+bitexact", str(submitted),
        )
        validate_webm(submitted, media.inspection)
        return submitted.read_bytes()


def validate_webm(path, inspection):
    """Verify the submitted WebM against the inspection clock and source frame hashes."""
    output = ingest(path)
    if (output.time_base != inspection.clip_time_base
            or output.last_frame_duration_pts != inspection.clip_last_frame_duration_pts
            or output.frame_pts != tuple(f.clip_pts for f in inspection.frames)):
        raise VideoError("Gemini WebM timestamps differ from the verified clip")
    for frame, pixels in zip(inspection.frames, _decode(output, range(len(output.frame_pts))), strict=True):
        if hashlib.sha256(pixels).hexdigest() != frame.source.rgb24_sha256:
            raise VideoError("Gemini WebM pixels differ from the verified source")


def _png(rgb: bytes, width: int, height: int) -> bytes:
    return _run(
        "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
        f"{width}x{height}", "-i", "pipe:0", "-frames:v", "1", "-threads", "1",
        "-f", "image2pipe", "-c:v", "png", "pipe:1", input_bytes=rgb,
    ).stdout


class GeminiAdapter:
    """Prepare media locally and implement ObservationProvider with the official SDK."""

    def __init__(self, *, client=None, model=None, clip_fps=2.0, sdk_version=None, single_request=False):
        if not 0 < clip_fps <= 24:
            raise VideoError("Clip sampling FPS must be in (0, 24]")
        self.client = client
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self.clip_fps = clip_fps
        self.sdk_version = sdk_version
        self.single_request = single_request

    @classmethod
    def from_env(cls, *, authorized: bool, client_args=None, **kwargs):
        if authorized is not True:
            raise VideoError("Explicit authorization is required before sending footage to Gemini")
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise VideoError("Set GEMINI_API_KEY or GOOGLE_API_KEY for the authorized run")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise VideoError("Install requirements-e1.txt for live Gemini inference") from exc
        http_options = types.HttpOptions(
            api_version="v1beta", timeout=90_000, client_args=client_args,
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        return cls(
            client=genai.Client(api_key=key, vertexai=False, http_options=http_options),
            sdk_version=version("google-genai"), **kwargs,
        )

    def prepare(self, request: ObservationRequest) -> PreparedGemini:
        validate_request(request)
        media = request.media
        common = (
            f"{request.prompt}\nUse only visible evidence. Do not infer identity, ownership, "
            "intent or actions outside the supplied media. State visibility limits and timing "
            "uncertainty. Return an empty observations list if no category applies."
            + (" Set possible_category on every observation: for insufficient_evidence, the event category you "
               "suspect but could not confirm, or none if no specific event is suspected; for every other "
               "category, none." if request.possible_category else "")
        )
        if isinstance(media, FrameSequenceInput):
            rule = (
                "Cite one or more supplied frame labels for each observation and leave "
                "clip_interval_us empty. Discrete frames do not show continuous action."
            )
            if request.relational:
                rule += (
                    f" Optionally propose one visual relation from these {media.width}x{media.height} images. "
                    "Use apparent image-plane convergence (approach), local visible divergence, or near "
                    "proximity (nearby). Return null if no relevant assessment is possible. Use unresolved "
                    "when an overlap or occlusion leaves correspondence uncertain. Never infer identity links "
                    "or same-pair separation. Cite chronological F labels. The half-open interval starts at "
                    "the first cited timestamp and ends one microsecond after the last; for nearby cite only "
                    "one view and set nearby_frame_label. Use two visible comparable pixel positions and "
                    "a radius in pixels covering each position's uncertainty. Use null marks on a view you "
                    "cannot assess. Never guess coordinates or uncertainty. Set distinct_paths true only "
                    "if two distinguishable paths are visible."
                )
            parts = [{"text": f"{common}\n{rule}"}]
            for i, (frame, pixels) in enumerate(zip(media.inspection.frames, media.rgb24_frames, strict=True), 1):
                parts.append({"text": f"F{i}: source time {frame.source_time_us} microseconds."})
                parts.append({"inline_data": {"mime_type": "image/png", "data": _png(pixels, media.width, media.height)}})
            media_map = asdict(media.inspection)
        else:
            rule = (
                "Cite approximate clip-relative bounds as clip_interval_us [start,end] in integer "
                f"microseconds, with 0 <= start < end <= {media.inspection.clip_duration_us}. "
                "Leave frame_labels empty. Do not claim timestamps more precise than the visible samples."
            )
            parts = [
                {"text": f"{common}\n{rule}"},
                {"inline_data": {"mime_type": "video/webm", "data": _webm(media)},
                 "video_metadata": {"fps": self.clip_fps}},
            ]
            media_map = asdict(media.inspection)
        encoded_bytes = sum(
            4 * ((len(p["inline_data"]["data"]) + 2) // 3) if "inline_data" in p
            else len(p["text"].encode("utf-8"))
            for p in parts
        )
        config = {
            "response_mime_type": "application/json",
            "response_json_schema": _response_schema(
                request.categories, len(media.inspection.frames) if request.relational else None,
                possible_category=request.possible_category,
            ),
            "max_output_tokens": 8192,
            "thinking_config": {"thinking_level": "HIGH"},
        }
        if encoded_bytes + len(json.dumps(config).encode("utf-8")) > MAX_INLINE_BYTES:
            raise VideoError("Gemini inline payload exceeds the E1 request size limit")
        media_map["ffmpeg_version"] = _version("ffmpeg")
        return PreparedGemini(
            request, [{"role": "user", "parts": parts}], config, media_map,
            single_request=self.single_request,
        )

    def infer(self, request: ObservationRequest) -> ObservationResult:
        return self.infer_prepared(self.prepare(request))

    def infer_prepared(self, prepared: PreparedGemini) -> ObservationResult:
        if self.client is None:
            raise VideoError("No authorized Gemini client is configured")
        config = prepared.config
        if prepared.single_request:
            # SDK-local option. It is omitted from the Gemini wire payload.
            config = {**config, "automatic_continuation": False}
        start = time.monotonic()
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=prepared.contents, config=config,
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            status = f" HTTP {code}" if type(code) is int else ""
            raise GeminiFailure(
                f"Gemini request failed ({type(exc).__name__}{status})",
                self._metadata(prepared, start),
                diagnostics={"error_type": type(exc).__name__, **({"http_status": code} if type(code) is int else {})},
            ) from None
        metadata = self._metadata(prepared, start, response)
        raw = None
        details = None
        try:
            raw = response.text
            dump = getattr(response, "model_dump", None)
            if dump is not None:
                details = dump(mode="json", exclude_none=True)
            candidates = getattr(response, "candidates", None)
            if candidates is not None and (
                len(candidates) != 1 or candidates[0].finish_reason != "STOP"
            ):
                raise VideoError("Gemini did not return one normally completed candidate")
            return self._parse(prepared.request, raw, metadata, details)
        except (ValueError, TypeError, KeyError) as exc:
            raise GeminiFailure(
                f"Invalid Gemini output: {exc}", metadata, raw, details, stage="validation",
                diagnostics=completion_diagnostics(response),
            ) from exc

    def _metadata(self, prepared, start, response=None, prompt_version=PROMPT_VERSION):
        input_metadata = []
        if isinstance(prepared.request.media, ClipInput):
            fps = prepared.contents[0]["parts"][-1]["video_metadata"]["fps"]
            input_metadata.append(("requested_video_fps", fps))
        usage = getattr(response, "usage_metadata", None)
        return InferenceMetadata(
            "google-gemini-developer-api", self.model, getattr(response, "model_version", None),
            ADAPTER_VERSION, prompt_version,
            (("sdk_version", self.sdk_version), ("max_output_tokens", prepared.config.get("max_output_tokens")),
             ("thinking_level", prepared.config.get("thinking_config", {}).get("thinking_level")),
             *input_metadata),
            round((time.monotonic() - start) * 1000),
            tuple((key, value) for key in USAGE_FIELDS
                  if type(value := getattr(usage, key, None)) is int),
        )

    def postures(self, request: PostureRequest) -> PostureResult:
        """Neutral posture probe: per frame, every visible person's posture, identifier and position."""
        if self.client is None:
            raise VideoError("No authorized Gemini client is configured")
        media = request.media
        validate_request(ObservationRequest(media, request.vocabulary, request.prompt))
        parts = [{"text": request.prompt + " Use only visible evidence. Do not infer identity, intent or events."}]
        for i, (frame, pixels) in enumerate(zip(media.inspection.frames, media.rgb24_frames, strict=True), 1):
            parts.append({"text": f"F{i}: source time {frame.source_time_us} microseconds."})
            parts.append({"inline_data": {"mime_type": "image/png", "data": _png(pixels, media.width, media.height)}})
        labels = [f"F{i}" for i in range(1, len(media.inspection.frames) + 1)]
        person = _object({"id": {"type": "string"}, "posture": {"type": "string", "enum": list(request.vocabulary)},
                          "x": {"type": "number"}, "y": {"type": "number"}, "w": {"type": "number"},
                          "h": {"type": "number"}, "seat_nearby": {"type": "boolean"}})
        config = {
            "response_mime_type": "application/json",
            "response_json_schema": _object({"frames": {
                "type": "array", "minItems": len(labels), "maxItems": len(labels),
                "items": _object({"frame_label": {"type": "string", "enum": labels},
                                  "persons": {"type": "array", "items": person}})}}),
            "max_output_tokens": 8192,
            "thinking_config": {"thinking_level": "HIGH"},
        }
        encoded = sum(4 * ((len(p["inline_data"]["data"]) + 2) // 3) if "inline_data" in p else len(p["text"].encode())
                      for p in parts)
        if encoded + len(json.dumps(config).encode("utf-8")) > MAX_INLINE_BYTES:
            raise VideoError("Gemini inline payload exceeds the E1 request size limit")
        prepared = PreparedGemini(ObservationRequest(media, request.vocabulary, request.prompt),
                                  [{"role": "user", "parts": parts}], config, {}, single_request=self.single_request)
        start = time.monotonic()
        try:
            response = self.client.models.generate_content(model=self.model, contents=prepared.contents, config=config)
        except Exception as exc:
            code = getattr(exc, "code", None)
            raise GeminiFailure(
                f"Gemini request failed ({type(exc).__name__}{f' HTTP {code}' if type(code) is int else ''})",
                self._metadata(prepared, start, prompt_version=POSTURE_PROMPT_VERSION),
                diagnostics={"error_type": type(exc).__name__, **({"http_status": code} if type(code) is int else {})},
            ) from None
        metadata = self._metadata(prepared, start, response, prompt_version=POSTURE_PROMPT_VERSION)
        raw = None
        try:
            raw = response.text
            candidates = getattr(response, "candidates", None)
            if candidates is not None and (len(candidates) != 1 or candidates[0].finish_reason != "STOP"):
                raise VideoError("Gemini did not return one normally completed candidate")
            data = json.loads(raw)
            entries = data["frames"] if isinstance(data, dict) and data.keys() == {"frames"} else None
            if not isinstance(entries, list) or [e.get("frame_label") for e in entries] != labels:
                raise VideoError("Expected one posture entry per submitted frame, in order")
            frames = tuple({"frame_id": frame.id, "persons": tuple(entry["persons"])}
                           for frame, entry in zip(media.inspection.frames, entries, strict=True))
            result = PostureResult(metadata, frames, raw)
            validate_postures(request, result)
            return result
        except (ValueError, TypeError, KeyError, VideoError) as exc:
            raise GeminiFailure(f"Invalid Gemini posture output: {exc}", metadata, raw, stage="validation",
                                diagnostics=completion_diagnostics(response)) from exc

    def floor_assessment(self, prompt: str):
        """System's assessment of a person-on-floor incident: one sentence from timed postures, text only, no image.
        Returns (sentence, metadata dict). The sentence is checked by floor_check.check_assessment before display."""
        if self.client is None:
            raise VideoError("No authorized Gemini client is configured")
        config = {
            "response_mime_type": "application/json",
            "response_json_schema": _object({"assessment": {"type": "string"}}),
            "max_output_tokens": 2048,
            "thinking_config": {"thinking_level": "LOW"},
        }
        if self.single_request:
            config = {**config, "automatic_continuation": False}
        start = time.monotonic()

        def metadata(response=None):
            usage = getattr(response, "usage_metadata", None)
            return {"provider": "google-gemini-developer-api", "model_id": self.model,
                    "model_version": getattr(response, "model_version", None), "adapter_version": ADAPTER_VERSION,
                    "prompt_version": ASSESSMENT_PROMPT_VERSION, "thinking_level": "LOW",
                    "latency_ms": round((time.monotonic() - start) * 1000),
                    "usage": {key: value for key in USAGE_FIELDS if type(value := getattr(usage, key, None)) is int}}
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=[{"role": "user", "parts": [{"text": prompt}]}], config=config)
        except Exception as exc:
            code = getattr(exc, "code", None)
            raise GeminiFailure(f"Gemini request failed ({type(exc).__name__}{f' HTTP {code}' if type(code) is int else ''})",
                                metadata()) from None
        try:
            data = json.loads(response.text)
            if not isinstance(data, dict) or data.keys() != {"assessment"} or not isinstance(data["assessment"], str):
                raise VideoError("Expected one assessment string")
            return data["assessment"], metadata(response)
        except (ValueError, TypeError, VideoError) as exc:
            raise GeminiFailure(f"Invalid Gemini assessment output: {exc}", metadata(response)) from exc

    @staticmethod
    def _parse(request, raw, metadata, details):
        data = json.loads(raw) if isinstance(raw, str) else None
        allowed = {"observations", "relation"} if request.relational else {"observations"}
        if (not isinstance(data, dict) or not data.keys() <= allowed
                or not isinstance(data.get("observations"), list)):
            raise VideoError("Expected an observations array")
        inspection = request.media.inspection
        labels = {f"F{i}": frame.id for i, frame in enumerate(inspection.frames, 1)} if isinstance(
            request.media, FrameSequenceInput,
        ) else {}
        observations = []
        for i, item in enumerate(data["observations"]):
            expected = set(TEXT_FIELDS + EVIDENCE_FIELDS)
            optional = {"possible_category"} if request.possible_category else set()
            if (not isinstance(item, dict) or not expected <= set(item) <= expected | optional
                    or any(not isinstance(item[field], str) for field in TEXT_FIELDS)):
                raise VideoError("Observation fields differ from the expected schema")
            suspected = item.get("possible_category", "none")
            if optional and (not isinstance(suspected, str) or (
                    suspected != "none" and (suspected not in request.categories or suspected == "insufficient_evidence"))):
                raise VideoError("Invalid possible_category")
            suspected = suspected if item["category"] == "insufficient_evidence" and suspected != "none" else None
            frame_labels, bounds = (item[field] for field in EVIDENCE_FIELDS)
            if not isinstance(frame_labels, list) or not isinstance(bounds, list):
                raise VideoError("Evidence fields must be arrays")
            if isinstance(request.media, FrameSequenceInput):
                if (bounds or not frame_labels
                        or any(not isinstance(label, str) or label not in labels for label in frame_labels)):
                    raise VideoError("Invalid frame labels or citation modality")
                evidence = FrameReference(tuple(labels[label] for label in frame_labels))
            else:
                if frame_labels or len(bounds) != 2 or any(type(bound) is not int for bound in bounds):
                    raise VideoError("Invalid clip bounds or citation modality")
                evidence = ClipReference(Interval(*bounds))
            observations.append(Observation(
                _id("observation", inspection.id, i, item), inspection.id, item["category"],
                item["description"], evidence, item["visibility_limits"], item["uncertainty"],
                source_video_id=inspection.video_id, inference_metadata=metadata, possible_category=suspected,
            ))
        relation = relation_error = None
        if data.get("relation") is not None:
            try:
                relation = perception_review(data["relation"], inspection.frames,
                                             (request.media.width, request.media.height))
            except VideoError as exc:
                relation_error = str(exc)
        result = ObservationResult(metadata, tuple(observations), raw, response_details=details,
                                   relation=relation, relation_error=relation_error)
        validate_result(request, result)
        return result
