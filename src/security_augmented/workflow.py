"""Bounded, video-first investigation with an offline E1 evidence source."""

from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re

from .contracts import ClipInspection, FrameEvidence, Inspection, Interval, Video, VideoError
from .gemini import GeminiAdapter, GeminiFailure, validate_webm
from .observation import (
    ClipInput, FrameReference, FrameSequenceInput, InferenceMetadata, Observation, ObservationProvider,
    ObservationRequest, resolve_clip_reference, validate_result,
)
from .relations import RELATION_LABELS, Review
from .video import _decode, _run, extract_clip, ingest, sample

DIRECT_PERSON_LABELS = {
    "person_appeared": "A person became visible.",
    "person_moved": "A person moved within view.",
    "person_fell": "A person went from upright to lying on the floor.",
}
# A person-entry candidate may only be narrowed to these weaker visibility claims.
ENTRY_REFINEMENT_LABELS = ("person_appeared", "person_moved")
VISUAL_TRANSITION_LABELS = {
    **DIRECT_PERSON_LABELS,
    "object_appeared": "An object became visible.",
    "object_disappeared": "An object ceased to be visible.",
}
_ACTION_LABELS = {
    "object_placed": "An object was placed.",
    "object_removed": "An object was removed.",
    "person_enters_area": "A person entered the observed area.",
}
EVENT_LABELS = _ACTION_LABELS | VISUAL_TRANSITION_LABELS
# Routine person activity fills candidate slots only after every visible security-relevant observation.
ROUTINE_LABELS = frozenset({"person_appeared", "person_moved"})
PRIORITY_LABELS = tuple(label for label in EVENT_LABELS if label not in ROUTINE_LABELS)
# Every category model-guided Perception may return: the single source for downstream vocabularies.
PERCEPTION_CATEGORIES = (*EVENT_LABELS, "insufficient_evidence")
RELATIONAL_TASK_CATEGORY = "relational_task"
_CLOCK = re.compile(r"(?<!\d)(?:\d+:)?\d{1,2}:[0-5]\d(?:\.\d{1,6})?(?!\d)")
_SECONDS_RANGE = re.compile(
    r"\b(?:between|from)\s+(\d+(?:\.\d{1,6})?)\s*(?:seconds?\s+)?"
    r"(?:and|to)\s+(\d+(?:\.\d{1,6})?)\s+seconds?\b"
)
_VISUAL_CHANGES = re.compile(r"\b(?:visual|visible|visibility)\s+changes?\b|\bchanges? in visibility\b")


@dataclass(frozen=True)
class Budget:
    max_archive_attempts: int = 24
    max_candidates: int = 12
    max_inspections: int = 4
    max_initial_windows: int = 12
    max_agent_calls: int = 24
    max_retrievals: int = 3
    max_verification_iterations: int | None = None
    max_failures: int | None = None
    max_recoveries: int = 1
    # Inspections rejected before dispatch cost no provider call and get their own feedback round.
    max_rejection_recoveries: int = 1
    # Initial observations shown to Investigation before it must search (archived runs used 8).
    max_visible_observations: int = 8
    # Compact Investigation requests: observation IDs shown as O1..On and a pre-send response schema size
    # bound. Long IDs overflowed Gemini's response grammar (HTTP 400). Archived replays keep the old requests.
    short_observation_ids: bool = False

    def __post_init__(self):
        optional = {"max_verification_iterations", "max_failures"}
        flags = {"short_observation_ids"}
        if any(type(getattr(self, name)) is not bool for name in flags) or any(
            (type(value) is not int or value < 0)
            for name, value in asdict(self).items()
            if name not in flags and (value is not None or name not in optional)
        ):
            raise VideoError("Investigation budgets must be nonnegative integers")


@dataclass(frozen=True)
class InspectionPlan:
    window_us: int = 10_000_000
    frame_step_us: int = 500_000

    def __post_init__(self):
        if (type(self.window_us) is not int or not 1 <= self.window_us <= 10_000_000
                or type(self.frame_step_us) is not int or self.frame_step_us < 500_000):
            raise VideoError("Inspection windows must be at most 10 seconds and frame steps at least 500 ms")


@dataclass(frozen=True)
class VideoCoverage:
    plan: InspectionPlan
    initial_scan: str
    initial_scan_end_us: int
    examined: tuple[Interval, ...]
    uninspected: tuple[Interval, ...]


@dataclass(frozen=True)
class Citation:
    video_id: str
    inspection_id: str
    modality: str
    interval: Interval
    frames: tuple[FrameEvidence, ...]


@dataclass(frozen=True)
class Finding:
    observation: Observation
    citation: Citation


@dataclass(frozen=True)
class ArchivedInspection:
    path: str
    modality: str
    interval: Interval
    status: str
    findings: tuple[Finding, ...] = ()
    error: str | None = None
    coverage: tuple[Interval, ...] = ()
    phase: str | None = None
    inspection: Inspection | ClipInspection | None = None
    inference: InferenceMetadata | None = None
    failure_stage: str | None = None
    failure_diagnostics: dict | None = None
    relation: Review | None = None
    relation_error: str | None = None
    relational_raw_response: str | None = None


@dataclass(frozen=True)
class RelationalFinding:
    review_id: str
    claim: str
    interval: Interval
    status: str
    continuity: str
    reason: str
    citations: tuple[Citation, ...]
    source: str = "local_review"


@dataclass(frozen=True)
class Event:
    category: str
    interval: Interval
    verdict: str
    reason: str
    observation_ids: tuple[str, ...]
    citations: tuple[Citation, ...]
    relation: RelationalFinding | None = None


@dataclass(frozen=True)
class Decision:
    actor: str
    action: str
    reason: str
    observation_ids: tuple[str, ...] = ()
    recipient: str | None = None
    details: dict | None = None


@dataclass(frozen=True)
class Answer:
    text: str
    events: tuple[Event, ...] = ()
    inspection: Inspection | None = None
    anchor: Event | RelationalFinding | None = None


@dataclass(frozen=True)
class Analysis:
    video: Video
    evidence: tuple[ArchivedInspection, ...]
    observations: tuple[Finding, ...]
    timeline: tuple[Event, ...]
    unresolved: tuple[Event, ...]
    trace: tuple[Decision, ...]
    report: str
    budget: Budget
    completion: dict | None = None
    coverage: VideoCoverage | None = None
    # Operator review queue (alerts, not_alerted, counts); see review.py. Never used as evidence.
    review: dict | None = None

    def ask(self, question: str, *, inspect_missing: bool = False) -> Answer:
        return _answer(self, question, inspect_missing=inspect_missing)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(value):
    return json.loads(json.dumps(value))


def _overlaps(left: Interval, right: Interval) -> bool:
    return left.start_us < right.end_us and right.start_us < left.end_us


def _load_archive(video: Video, paths: Iterable[Path], budget: Budget) -> tuple[ArchivedInspection, ...]:
    attempts = sorted({path for root in paths for path in root.rglob("attempt-*.json")})
    if not attempts:
        raise VideoError("No archived attempts found")
    return tuple(_load_attempt(video, path) for path in attempts[:budget.max_archive_attempts])


def _load_attempt(video: Video, path: Path) -> ArchivedInspection:
    attempt = _json(path)
    manifest = _json(path.with_name("request.json"))
    record = manifest["inspection"]
    interval = Interval(**record["requested_interval"])
    interval.validate(video.duration_us)
    mode = record["modality"]
    if record["video_id"] != video.id or mode not in {"frames", "clip"}:
        raise VideoError(f"Archive does not match source or modality: {path}")
    if attempt["status"] != "success":
        return ArchivedInspection(str(path), mode, interval, "failed", error=attempt.get("error"))
    metadata = InferenceMetadata(**attempt["metadata"])
    if metadata.model_id != manifest["model"]:
        raise VideoError(f"Archived request and response model differ: {path}")

    content, = manifest["contents"]
    parts = content["parts"]
    media_parts = [part["inline_data"] for part in parts if "inline_data" in part]
    for part in media_parts:
        name = part["path"]
        if Path(name).name != name:
            raise VideoError("Archived media must be beside its request manifest")
        payload = path.with_name(name).read_bytes()
        if len(payload) != part["bytes"] or hashlib.sha256(payload).hexdigest() != part["sha256"]:
            raise VideoError(f"Archived media hash or size differs: {name}")

    if mode == "clip":
        inspection, artifact = extract_clip(video, interval)
        part, = media_parts
        if part["mime_type"] != "video/webm":
            raise VideoError("Expected archived WebM")
        validate_webm(path.with_name(part["path"]), inspection)
        media = ClipInput(inspection, artifact)
    else:
        inspection = sample(video, interval, record["requested_times_us"])
        frames = inspection.frames
        pixels = _decode(video, tuple(frame.display_index for frame in frames))
        if len(parts) != 1 + 2 * len(frames):
            raise VideoError("Archived PNG count differs from inspection")
        for index, (frame, blob) in enumerate(zip(frames, media_parts, strict=True), 1):
            if parts[2 * index - 1] != {"text": f"F{index}: source time {frame.source_time_us} microseconds."}:
                raise VideoError("Archived frame label differs from source evidence")
            if blob["mime_type"] != "image/png":
                raise VideoError("Expected archived PNG")
            png = _run(
                "ffmpeg", "-v", "error", "-i", str(path.with_name(blob["path"])),
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "pipe:1",
            ).stdout
            if png != pixels[index - 1]:
                raise VideoError("Archived PNG pixels differ from source")
        media = FrameSequenceInput(inspection, video.width, video.height, pixels)

    if _normalize(asdict(inspection)) != {k: v for k, v in record.items() if k != "ffmpeg_version"}:
        raise VideoError(f"Archived inspection differs from source replay: {path}")
    schema = manifest["config"]["response_json_schema"]
    categories = tuple(schema["properties"]["observations"]["items"]["properties"]["category"]["enum"])
    request = ObservationRequest(media, categories, parts[0]["text"])
    details = attempt.get("response_details")
    if not details or [c.get("finish_reason") for c in details.get("candidates", ())] != ["STOP"]:
        raise VideoError(f"Archive lacks a normally completed model response: {path}")
    result = GeminiAdapter._parse(request, attempt["raw_response"], metadata, details)
    if _normalize([asdict(obs) for obs in result.observations]) != attempt["observations"]:
        raise VideoError(f"Archived normalized observations differ from raw response: {path}")

    return ArchivedInspection(
        str(path), mode, interval, "success", _findings(video, inspection, result),
        coverage=_coverage(inspection),
    )


def _coverage(inspection):
    if isinstance(inspection, ClipInspection):
        return (inspection.actual_source_interval,)
    return tuple(Interval(f.source_time_us, f.source_time_us + 1) for f in inspection.frames)


def _findings(video, inspection, result):
    findings = []
    for obs in result.observations:
        if isinstance(obs.evidence, FrameReference):
            cited = set(obs.evidence.frame_ids)
            frames = tuple(frame for frame in inspection.frames if frame.id in cited)
        else:
            frames = resolve_clip_reference(inspection, obs.evidence)
        support = Interval(frames[0].source_time_us, frames[-1].source_time_us + 1)
        findings.append(Finding(obs, Citation(video.id, inspection.id, inspection.modality, support, frames)))
    return tuple(findings)


class InvestigationAgent:
    """Choose candidate events and intervals from initial frame observations."""

    def propose(self, findings: tuple[Finding, ...], limit: int, trace: list[Decision]):
        candidates = []
        for finding in sorted(findings, key=lambda f: f.citation.interval.start_us):
            if len(candidates) >= limit:
                trace.append(Decision("investigation", "budget_exhausted", "Candidate limit reached."))
                break
            obs = finding.observation
            if obs.category not in _ACTION_LABELS and obs.category != "insufficient_evidence":
                trace.append(Decision("investigation", "skip", "Category outside event taxonomy.", (obs.id,)))
                continue
            candidates.append(finding)
            reason = "Request complementary clip evidence for the cited interval."
            trace.append(Decision("investigation", "propose", reason, (obs.id,), "verification"))
        return candidates


class VerificationAgent:
    """Reinspect candidate intervals with complementary, source-verified evidence."""

    def verify(self, candidates, inspect, limit, trace):
        inspections = 0
        events = []
        for finding in candidates:
            obs = finding.observation
            initial = finding.citation
            supporting = (finding,)
            verdict = "insufficient"
            if inspections == limit:
                reason = "Complementary inspection budget exhausted."
                trace.append(Decision("verification", "budget_exhausted", reason, (obs.id,)))
            else:
                inspections += 1
                trace.append(Decision(
                    "verification", "inspect",
                    f"Inspect clips overlapping [{initial.interval.start_us}, "
                    f"{initial.interval.end_us}) µs.", (obs.id,),
                ))
                # Require overlap in the cited frames, not just the archive's request window.
                alternatives = tuple({
                    f.observation.id: f
                    for entry in inspect(initial.interval) if entry.modality == "clip" and entry.status == "success"
                    and _overlaps(entry.interval, initial.interval)
                    for f in entry.findings if _overlaps(f.citation.interval, initial.interval)
                }.values())
                trace.append(Decision(
                    "verification", "tool_result", f"{len(alternatives)} overlapping clip observations.",
                    tuple(f.observation.id for f in alternatives),
                ))
                same = tuple(f for f in alternatives if f.observation.category == obs.category)
                incompatible = tuple(
                    f for f in alternatives
                    if f.observation.category in _ACTION_LABELS and f.observation.category != obs.category
                )
                if obs.category == "insufficient_evidence":
                    reason = "Initial observation is ambiguous. Overlapping context alone does not resolve it."
                elif incompatible:
                    reason = "Overlapping evidence reports a different event category; correspondence is unresolved."
                    supporting += incompatible
                elif same:
                    supporting += same
                    verdict = "supported"
                    reason = "Frame and clip observations agree on category in overlapping source evidence."
                else:
                    reason = "No overlapping clip observation corroborates this candidate."
            ids = tuple(f.observation.id for f in supporting)
            event = Event(obs.category, initial.interval, verdict, reason, ids, tuple(f.citation for f in supporting))
            events.append(event)
            trace.append(Decision("verification", "verdict", f"{verdict}: {reason}", ids, "reporting"))
        return tuple(events)


def _time(us: int) -> str:
    minutes, remainder = divmod(us, 60_000_000)
    seconds, fraction = divmod(remainder, 1_000_000)
    return f"{minutes:02d}:{seconds:02d}.{fraction:06d}"



def _supported_timeline(events):
    """Include accepted spatial evidence at its own time even if its host movement failed."""
    supported = []
    relations = {}
    for event in events:
        if event.verdict == "supported" and event.category != RELATIONAL_TASK_CATEGORY:
            supported.append(event)
        relation = event.relation
        if (relation and relation.status == "supported" and relation.citations
                and (relation.claim != "separation" or relation.continuity == "reviewed")):
            relations[relation.review_id] = Event(
                RELATIONAL_TASK_CATEGORY, relation.interval, "supported", relation.reason,
                event.observation_ids, relation.citations, relation,
            )
    return tuple(sorted((*supported, *relations.values()), key=lambda event: event.interval.start_us))


def _event_label(event):
    if event.category == RELATIONAL_TASK_CATEGORY:
        return RELATION_LABELS[event.relation.claim]
    return EVENT_LABELS[event.category]


class ReportingAgent:
    """Render bounded claims and cite the exact supporting inspections."""

    def render(self, video, events, trace, *, include_reasons=True, include_supported_rationales=False):
        support_policy = (
            "Direct visual findings use a model-assessed before/after frame pair. "
            "Action claims require corroborating observations from separate inspections."
            if any(event.category in VISUAL_TRANSITION_LABELS for event in events)
            else "Physical action findings require corroborating observations from separate inspections, "
                 "which may come from the same model."
        )
        if any(event.relation for event in events):
            support_policy += " Relational findings carry separate source-frame evidence."
        lines = [
            "# Video investigation",
            "",
            f"Source: {video.id}  ",
            f"SHA-256: `{video.sha256}`",
            "",
            "This report covers only the inspected visual inputs. Citation times describe evidence. "
            + support_policy,
            "",
        ]
        for event in events:
            label = ("Relational finding" if event.category == RELATIONAL_TASK_CATEGORY
                     else _event_label(event) if event.verdict == "supported" else "Finding remains unresolved.")
            start = _time(event.interval.start_us)
            end = _time(event.interval.end_us - 1)
            reason = f": {event.reason}" if include_reasons else ""
            if event.verdict == "insufficient" and not include_reasons:
                reason = ". Recorded reason: " + re.sub(r"([\\`*_\[\]<>])", r"\\\1", " ".join(event.reason.split()))
            lines.append(f"- **{start}–{end}** {label} {event.verdict}{reason}")
            if include_supported_rationales and event.verdict == "supported" and event.reason.strip():
                rationale = re.sub(r"([\\`*_\[\]<>])", r"\\\1", " ".join(event.reason.split()))
                lines.append(f"  - Verification rationale (model assessment): {rationale}")
            for cite in event.citations:
                lines.append(
                    f"  - {cite.modality} `{cite.inspection_id}` at "
                    f"{_time(cite.frames[0].source_time_us)}–{_time(cite.frames[-1].source_time_us)} "
                    f"({len(cite.frames)} source frames)."
                )
            if event.relation is not None:
                relation = event.relation
                label = (RELATION_LABELS[relation.claim] if relation.status == "supported"
                         else "Relationship unresolved")
                continuity = ("Continuity under reviewed correspondence" if relation.continuity == "reviewed"
                              else "Person continuity unresolved")
                ids = ", ".join(f"`{frame.id}`" for cite in relation.citations for frame in cite.frames)
                source = ("Targeted perception assessment" if relation.source == "targeted_perception"
                          else "Local visual review")
                rationale = relation.reason
                if relation.source == "targeted_perception" and rationale.startswith("Reviewer observed "):
                    rationale = rationale.replace("Reviewer observed ", "Perception proposed ", 1)
                lines.append(
                    f"  - {label} {_event_reference(relation)} {continuity}. "
                    f"{source}. {rationale}. Source frames: {ids}."
                )
        if not events:
            lines.append("No supported events were established from the available evidence.")
        trace.append(Decision("reporting", "render", f"Rendered {len(events)} verified or unresolved items."))
        return "\n".join(lines) + "\n"


def _check_controller(controller, decide):
    if controller not in {"python", "langgraph"} or (decide is not None and not callable(decide)):
        raise VideoError("Select python or langgraph and a valid decision callable")
    if controller == "langgraph":
        if decide is None:
            raise VideoError("LangGraph requires a decision callable")
        from .graph_workflow import require_graph

        require_graph()


def analyze_archive(source: Path, archives: Iterable[Path], *, budget: Budget = Budget(), decide=None, controller="python") -> Analysis:
    """Start an offline investigation from the uploaded source, with no question."""
    video = ingest(source)
    evidence = _load_archive(video, archives, budget)
    return _analyze_archive_snapshot(video, evidence, budget, decide=decide, controller=controller)


def _analyze_archive_snapshot(video, evidence, budget, *, decide=None, controller="python"):
    return _analyze(
        video, evidence,
        lambda interval, modality: tuple(
            e for e in evidence if e.modality == modality and (
                _overlaps(e.interval, interval)
                or (decide is not None and any(_overlaps(span, interval) for span in e.coverage))
            )
        ),
        budget, decide=decide, controller=controller,
    )


def _video_coverage(video, evidence, plan, scan, initial_end):
    examined = []
    for span in sorted(
        (span for entry in evidence if entry.status == "success" for span in entry.coverage),
        key=lambda span: span.start_us,
    ):
        end = min(span.end_us, video.duration_us)
        if span.start_us >= end:
            continue
        if examined and span.start_us <= examined[-1].end_us:
            last = examined[-1]
            examined[-1] = Interval(last.start_us, max(last.end_us, end))
        else:
            examined.append(Interval(span.start_us, end))

    uninspected = []
    cursor = 0
    for span in examined:
        if cursor < span.start_us:
            uninspected.append(Interval(cursor, span.start_us))
        cursor = span.end_us
    if cursor < video.duration_us:
        uninspected.append(Interval(cursor, video.duration_us))
    return VideoCoverage(plan, scan, initial_end, tuple(examined), tuple(uninspected))


def _observe_video(video, provider, interval, modality, phase, plan, *, model_guided, relational=False, sampling_step_ms=None, visual_question=None):
    """Run one source inspection using the video-first perception contract."""
    inspection = None
    metadata = None
    stage = "preparation"
    try:
        if sampling_step_ms is not None and (
            phase != "targeted" or modality != "frames" or type(sampling_step_ms) is not int
            or sampling_step_ms not in (500, 250)
        ):
            raise VideoError("Sampling overrides apply only to targeted frame inspections at 500 or 250 ms")
        if modality == "clip":
            media = ClipInput(*extract_clip(video, interval))
        else:
            step_us = plan.frame_step_us if sampling_step_ms is None else sampling_step_ms * 1000
            times = list(range(interval.start_us, interval.end_us, step_us))
            inspection = sample(video, interval, times)
            pixels = _decode(video, tuple(f.display_index for f in inspection.frames))
            media = FrameSequenceInput(inspection, video.width, video.height, pixels)
        inspection = media.inspection
        request = ObservationRequest(
            media, PERCEPTION_CATEGORIES if model_guided else (*_ACTION_LABELS, "insufficient_evidence"),
            "Describe visible activities. Use placement, removal or entry only when the "
            "observable transition is established. Describe uncertain action as insufficient evidence. "
            "Cite the supporting visual evidence. Do not infer ownership, intent or abandonment."
            + (
                " Use object_appeared or object_disappeared for visibility changes without an observed "
                "physical action. Describe the visible before and after states and cite frames for both. "
                "Use object_placed or object_removed only when the physical action itself is visible. "
                "Use person_appeared for first visibility and person_moved for motion already within view. "
                "Use person_fell only when cited frames show the same person upright before and lying on the "
                "floor after; cite frames for both states. A person sitting, crouching, bending or partly hidden "
                "is insufficient evidence. Do not infer injury, medical condition or cause. "
                "Use person_enters_area only when a person visibly crosses an identifiable physical boundary. "
                "Name the boundary and describe the crossing in the observation. The image edge only marks visibility."
                if model_guided else ""
            )
            + (
                " For this targeted inspection, report only visible cues. Cite frames that show changes "
                "and describe what is visible before and after. If several people are visible, describe "
                "their positions and paths separately where distinguishable. Flag occlusion, frame edges "
                "and uncertainty about identity across a visibility gap. Do not infer separation from a "
                "person becoming hard to see."
                if phase == "targeted" and model_guided else ""
            )
            + (f" Inspection question (an unverified lead): {visual_question}" if visual_question else ""),
            relational=relational,
        )
        stage = "inference"
        result = provider.infer(request)
        stage = "validation"
        metadata = result.metadata
        validate_result(request, result)
        entry = ArchivedInspection(
            "provider", modality, interval, "success", _findings(video, inspection, result),
            coverage=_coverage(inspection), phase=phase, inspection=inspection, inference=metadata,
            relation=result.relation, relation_error=result.relation_error,
            relational_raw_response=result.raw_response if relational else None,
        )
    except VideoError as exc:
        diagnostics = None
        if isinstance(exc, GeminiFailure):
            stage = exc.stage
            metadata = exc.metadata
            diagnostics = exc.diagnostics
        entry = ArchivedInspection(
            "provider", modality, interval, "failed", error=str(exc), phase=phase, inspection=inspection,
            inference=metadata, failure_stage=stage, failure_diagnostics=diagnostics,
        )
    return entry

def analyze_video(
    source: Path, provider: ObservationProvider, *, budget: Budget = Budget(),
    plan: InspectionPlan = InspectionPlan(), decide=None, controller="python", movement_only=False, adaptive_sampling=True,
) -> Analysis:
    """Analyze a new video using a caller-supplied, authorized observation provider."""
    _check_controller(controller, decide)
    video = ingest(source)
    evidence = []

    def observe(interval, modality, phase, *, relational=False, sampling_step_ms=None, visual_question=None):
        entry = _observe_video(video, provider, interval, modality, phase, plan,
                               model_guided=decide is not None, relational=relational, sampling_step_ms=sampling_step_ms, visual_question=visual_question)
        evidence.append(entry)
        return entry

    window_us = plan.window_us
    for start in range(0, min(video.duration_us, budget.max_initial_windows * window_us), window_us):
        observe(Interval(start, min(start + window_us, video.duration_us)), "frames", "initial")

    def inspect(interval, modality, *, relational=False, sampling_step_ms=None, visual_question=None):
        if decide is not None:
            return (observe(interval, modality, "targeted", relational=relational, sampling_step_ms=sampling_step_ms, visual_question=visual_question),)
        context = Interval(
            max(0, interval.start_us - 500_000),
            min(video.duration_us, interval.end_us + 500_000, interval.start_us + window_us),
        )
        return (observe(context, "clip", "targeted"),)

    initial_end = evidence[-1].interval.end_us if evidence else 0
    successful = sum(entry.status == "success" for entry in evidence)
    initial_scan = (
        "completed" if successful and successful == len(evidence) and initial_end == video.duration_us
        else "partial" if successful else "failed"
    )
    analysis = _analyze(
        video, evidence, inspect, budget, decide=decide, controller=controller, initial_scan=initial_scan,
        relational_tasks=controller == "langgraph" and not movement_only,
        adaptive=controller == "langgraph" and adaptive_sampling,
    )
    coverage = _video_coverage(video, evidence, plan, initial_scan, initial_end)
    scan_note = (
        f"Initial scan: {coverage.initial_scan} (scheduled through {_time(coverage.initial_scan_end_us)} "
        f"of {_time(video.duration_us)}). "
        "Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. "
        "Uninspected time provides no evidence of absence. "
        "Corroboration from two inspections using the same model is not independent semantic confirmation."
    )
    report = analysis.report.replace("# Video investigation\n", f"# Video investigation\n\n{scan_note}\n", 1)
    return replace(analysis, coverage=coverage, report=report)


def _analyze(video, evidence, inspect, budget, *, decide=None, controller="python", initial_scan=None, relational_tasks=False, adaptive=False):
    _check_controller(controller, decide)
    trace = [
        Decision(
            "workflow", "ingest",
            f"Verified source {video.id}; {len(evidence)} initial evidence records available.",
        )
    ]
    for entry in evidence:
        detail = f"{entry.modality} [{entry.interval.start_us}, {entry.interval.end_us}) µs: {entry.status}"
        if entry.error:
            detail += f" ({entry.error})"
        trace.append(Decision("workflow", "evidence_result", detail))
    initial = tuple({
        f.observation.id: f for entry in evidence if entry.modality == "frames" for f in entry.findings
    }.values())
    def traced_inspection(interval):
        entries = tuple(inspect(interval, "clip"))
        for entry in entries:
            if entry.modality == "clip" and entry.status == "failed" and _overlaps(entry.interval, interval):
                trace.append(Decision("verification", "tool_failure", entry.error or "Clip inspection failed."))
        return entries

    completion = None
    if decide is None:
        candidates = InvestigationAgent().propose(initial, budget.max_candidates, trace)
        events = VerificationAgent().verify(candidates, traced_inspection, budget.max_inspections, trace)
        events = tuple(sorted(events, key=lambda event: event.interval.start_us))
        report = ReportingAgent().render(video, events, trace)
    else:
        from .agents import AgentRun

        run = AgentRun(video, decide, inspect, budget, trace, initial_scan=initial_scan,
                       autonomous_relations=relational_tasks, relational_selection=relational_tasks,
                       relational_tasks=relational_tasks,
                       sampled_indices={frame.display_index for entry in evidence if entry.status == "success"
                                        for frame in entry.inspection.frames} if adaptive else None)
        if controller == "langgraph":
            from .graph_workflow import run_graph

            events, report = run_graph(run, initial)
        else:
            candidates = sorted(run.investigate(initial), key=lambda f: f.citation.interval.start_us)
            events = run.finalize_events(tuple(run.verify(finding) for finding in candidates))
            report = run.report(events)
        completion = run.completion()
    queue = None
    if decide is not None:
        from .review import render as render_review, review

        queue = review(events, trace, evidence)
        report = render_review(queue) + report
    return Analysis(
        video, tuple(evidence), initial,
        _supported_timeline(events),
        tuple(e for e in events if e.verdict != "supported"),
        tuple(trace), report, budget, completion, review=queue,
    )


def _clock_us(value: str) -> int:
    whole, _, fractional = value.partition(".")
    seconds = 0
    for part in whole.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds * 1_000_000 + int(fractional.ljust(6, "0"))


def _query_categories(text):
    categories = set()
    if re.search(r"\b(retriev\w*|remov\w*)\b|pick\w* up", text):
        categories.add("object_removed")
    if re.search(r"\bplac\w*\b|left behind|set down|put down", text):
        categories.add("object_placed")
    if re.search(r"\benter\w*\b", text):
        categories.add("person_enters_area")
    if re.search(r"\bappear\w*\b|became visible", text):
        categories.add("person_appeared" if re.search(r"\b(person|someone|people)\b", text) else "object_appeared")
    if re.search(r"\b(person|someone|people)\b", text) and re.search(r"\b(mov\w*|walk\w*)\b", text):
        if "person_enters_area" not in categories:
            categories.add("person_moved")
    if re.search(r"\b(fall|falls|falling|fell|fallen)\b|\b(lying|lay|lies) on the (floor|ground)\b", text):
        categories.add("person_fell")
    if re.search(r"\bdisappear\w*\b|ceased to be visible", text):
        categories.add("object_disappeared")
    if not categories and _VISUAL_CHANGES.search(text):
        categories.update(VISUAL_TRANSITION_LABELS)
    return categories


_EVENT_RELATIVE = re.compile(r"what (?:happened|occurred) (before|during|after) (.+?)[?!.]*$")
_PERSON_RELATION = re.compile(r"\b(?:approach\w*|converg\w*|join\w*|separat\w*|diverg\w*|follow\w*|interact\w*|meet(?:ing)?|met|together|same person|nearby|near (?:each other|one another))\b")
_ANCHOR_STOP_WORDS = {"a", "an", "the", "in", "on", "at", "of", "with", "was", "is"}


def _anchor_terms(text):
    return tuple(
        "move" if word.startswith("mov") else "walk" if word.startswith("walk") else
        "toward" if word == "towards" else word
        for word in re.findall(r"[a-z0-9]+", text.casefold()) if word not in _ANCHOR_STOP_WORDS
    )


_RELATIONAL_ANCHORS = {
    "approach": r"(?:the )?(?:two )?(?:people|pedestrians) approach(?:ed)? each other|approach|(?:apparent )?convergence(?: in the image)?",
    "nearby": r"(?:the )?(?:two )?(?:visible )?(?:people|pedestrians) (?:were |moved |move |walking |walk )?near each other|nearby movement",
    "visible_divergence": r"local divergence(?: in the image)?|(?:the )?(?:two )?(?:visible )?(?:paths|trajectories) diverg(?:e|ed)",
    "separation": r"(?:the )?(?:same )?(?:two )?(?:people|pedestrians) separat(?:e|ed)|same-pair separation",
}


def _relational_claim(description):
    return next((key for key, pattern in _RELATIONAL_ANCHORS.items()
                 if re.fullmatch(pattern, description.strip())), None)


def _event_relative_answer(analysis, relation, description):
    terms = _anchor_terms(description)
    categories = _query_categories(description)
    claim = _relational_claim(description)
    timeline = _supported_timeline((*analysis.timeline, *analysis.unresolved))
    # Only a typed, accepted relation can answer a guarded relationship query.
    if claim is None and _PERSON_RELATION.search(description):
        return Answer("No grounded matching event was found. The available findings do not establish that relationship.")
    if not terms or {"not", "never", "no"}.intersection(terms):
        return Answer("No grounded matching event was found for that reference.")
    observations = {finding.observation.id: finding for finding in analysis.observations}
    for inspection in analysis.evidence:
        observations.update((finding.observation.id, finding) for finding in inspection.findings)

    def matches(event):
        if event.category == RELATIONAL_TASK_CATEGORY or categories and event.category not in categories:
            return False
        if not event.citations:
            return False
        label = _anchor_terms(EVENT_LABELS[event.category])
        if terms == label:
            return True
        # Keep direction/location wording in order. Match action and actor terms separately
        # because a rationale may say "movement of the person."
        common = {"move", "walk", "person", "people", "someone"}
        details = " ".join(term for term in terms if term not in common)

        def describes(text):
            words = _anchor_terms(text)
            description_details = " ".join(word for word in words if word not in common)
            return set(terms) <= set(words) and (not details or f" {details} " in f" {description_details} ")

        return describes(event.reason) and any(
            describes(observations[identifier].observation.description)
            for identifier in event.observation_ids if identifier in observations
        )

    if claim is None:
        anchors = [event for event in timeline if matches(event)]
    else:
        anchors = [event.relation for event in timeline
                   if event.category == RELATIONAL_TASK_CATEGORY and event.relation.claim == claim]
    if not anchors:
        return Answer("No grounded matching event was found. Use a supported event description or a source time range.")
    if len(anchors) > 1:
        choices = "; ".join(_event_reference(event) for event in sorted(anchors, key=lambda e: e.interval.start_us))
        return Answer(f"Several grounded events match the reference. Specify a source interval: {choices}")
    anchor, = anchors
    boundary = anchor.interval
    events = []
    for event in (*timeline, *analysis.unresolved):
        if (event == anchor or not event.citations
                or claim is not None and event.category == RELATIONAL_TASK_CATEGORY
                and event.relation and event.relation.review_id == anchor.review_id):
            continue
        span = event.interval
        if (
            (relation == "before" and span.end_us <= boundary.start_us)
            or (relation == "after" and boundary.end_us <= span.start_us)
            or (relation == "during" and boundary.start_us <= span.start_us and span.end_us <= boundary.end_us)
        ):
            events.append(event)
    events.sort(key=lambda event: (event.interval.start_us, event.interval.end_us))
    anchor_label = RELATION_LABELS[claim] if claim is not None else EVENT_LABELS[anchor.category]
    lines = [f"Reference event: {anchor_label} {_event_reference(anchor)}"]
    if claim is not None and anchor.continuity == "unresolved":
        lines.append("The reference does not establish person continuity.")
    for event in events:
        label = (
            f"Recorded supported finding: {_event_label(event)}" if event.verdict == "supported"
            else f"Unresolved observation ({event.category}, {event.verdict})."
        )
        lines.append(f"- {label} {_event_reference(event)}")
    if not events:
        lines.append(f"No recorded findings fit strictly {relation} that evidence bracket.")
    lines.append("Results cover recorded evidence only. Temporal ordering alone cannot establish identity or continuity.")
    return Answer("\n".join(lines), tuple(events), anchor=anchor)


def _event_reference(event):
    bounds = event.interval
    inspections = ", ".join(dict.fromkeys(c.inspection_id for c in event.citations))
    return f"{_time(bounds.start_us)}–{_time(bounds.end_us - 1)} (source inspections: {inspections})."


def _answer(analysis: Analysis, question: str, *, inspect_missing: bool) -> Answer:
    text = question.casefold()
    if re.search(r"\babandon\w*\b|\bunattended\b|\bsuspicious\b", text):
        return Answer("The available evidence cannot establish abandonment, unattended duration or suspicious intent.")
    relative = _EVENT_RELATIVE.fullmatch(text.strip())
    if relative and not (_CLOCK.search(text) or _SECONDS_RANGE.search(text)):
        return _event_relative_answer(analysis, *relative.groups())
    if _PERSON_RELATION.search(text) and re.search(r"\b(afterward[s]?|then|subsequently)\b", text):
        return Answer("Insufficient evidence to establish person correspondence or continuity for that relative question.")
    source_times = _CLOCK.findall(text)
    if not source_times:
        source_times = [time for pair in _SECONDS_RANGE.findall(text) for time in pair]
    times = [_clock_us(clock) for clock in source_times]
    if len(times) > 2 or (len(times) == 2 and times[1] <= times[0]):
        return Answer("Use one source time or a start and end time in chronological order.")
    interval = None
    if times:
        interval = Interval(times[0], times[-1] if len(times) == 2 else times[0] + 1)
    categories = _query_categories(text)
    timeline = _supported_timeline((*analysis.timeline, *analysis.unresolved))
    scoped = tuple(e for e in timeline if interval is None or _overlaps(e.interval, interval))
    if _PERSON_RELATION.search(text):
        # Require the whole spatial claim to match. A compound question about joining or
        # identity must not receive an affirmative answer from an incidental movement.
        description = _SECONDS_RANGE.sub("", text)
        description = re.sub(r"\bat\s+" + _CLOCK.pattern, "", description)
        description = re.sub(r"^(?:did|do|were|are|was there|show(?: me)?)\s+", "", description.strip())
        claim = _relational_claim(description.rstrip("?!. "))
        matches = tuple(e for e in scoped
                        if e.category == RELATIONAL_TASK_CATEGORY and e.relation.claim == claim)
        if not matches:
            return Answer("Insufficient evidence for the requested relationship in the selected scope.")
        lines = [f"{_event_label(e)}. {_event_reference(e)}" for e in matches]
        if any(e.relation.continuity == "unresolved" for e in matches):
            lines.append("Person continuity remains unresolved.")
        return Answer(" ".join(lines), matches)
    events = tuple(e for e in scoped if not categories or e.category in categories)
    if not categories and not re.search(r"what (happened|occurred)|timeline|events?|summari[zs]e", text):
        words = set(re.findall(r"\w+", text)) - {"was", "were", "the", "did", "a", "an", "is", "there", "at"}
        events = tuple(
            e for e in events if words.intersection(
                re.findall(r"\w+", _event_label(e).casefold()),
            )
        )
    uninspected = interval is not None and analysis.coverage is not None and not any(
        _overlaps(interval, span) for span in analysis.coverage.examined
    )
    if not events:
        message = "No matching supported event was found. The available coverage does not establish absence."
        if interval is not None and interval.start_us >= analysis.video.duration_us:
            return Answer(f"{message} The requested time is outside the source video.")
        if uninspected:
            message += " The requested interval has no inspected evidence in the investigation."
        for action, transition, claim in (
            ("object_placed", "object_appeared", "physical placement"),
            ("object_removed", "object_disappeared", "physical removal"),
        ):
            if categories == {action} and any(e.category == transition for e in scoped):
                message += (
                    f" The timeline supports this visibility change: {EVENT_LABELS[transition]} "
                    f"This evidence does not establish {claim}."
                )
        if inspect_missing and interval is not None:
            try:
                interval.validate(analysis.video.duration_us)
                requested = sorted({
                    interval.start_us, (interval.start_us + interval.end_us) // 2, interval.end_us - 1,
                })
                inspection = sample(analysis.video, interval, requested)
            except VideoError as exc:
                return Answer(f"{message} Requested frame inspection unavailable: {exc}")
            return Answer(f"{message} A source-frame inspection is attached for review.", inspection=inspection)
        return Answer(message)
    message = " ".join(
        f"{_event_label(e)} Evidence bracket: {_time(e.interval.start_us)}–{_time(e.interval.end_us - 1)}."
        if e.category in VISUAL_TRANSITION_LABELS or e.category == RELATIONAL_TASK_CATEGORY else _event_label(e)
        for e in events
    )
    if uninspected:
        message += " The requested interval has no inspected evidence. The finding's exact time within its bracket is unknown."
    return Answer(message, events)


def _interactive(analysis):
    while True:
        try:
            question = input("\nQuestion (blank to exit): ").strip()
        except EOFError:
            break
        if not question:
            break
        print(json.dumps(asdict(analysis.ask(question, inspect_missing=True)), indent=2))


MAX_INITIAL_WINDOWS = 12  # safety cap for --max-initial-windows auto: two minutes at 10 s windows


def initial_window_count(duration_us, window_us, cap=MAX_INITIAL_WINDOWS):
    """Windows needed to scan the whole source, capped; a longer source stays a partial scan."""
    if duration_us <= 0 or window_us <= 0:
        raise VideoError("Duration and window must be positive")
    return min(cap, -(-duration_us // window_us))


def _window_count(value):
    import argparse

    if value == "auto":
        return value
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use 'auto' or an integer") from None
    if not 1 <= count <= MAX_INITIAL_WINDOWS:
        raise argparse.ArgumentTypeError(f"use 'auto' or 1-{MAX_INITIAL_WINDOWS}")
    return count


def _write_guard_report_safely(output, result):
    """report.html is derived from analysis.json; a failure there must not fail a completed analysis."""
    import sys

    try:
        from .guard_report import write

        write(output, json.loads(json.dumps(result)))
        return True
    except Exception as exc:  # noqa: BLE001 - presentation only; the analysis artifacts are already written
        print(f"warning: report.html was not generated ({type(exc).__name__}: {exc}). analysis.json and report.md "
              f"are complete. Regenerate with: python -m security_augmented.guard_report {output}", file=sys.stderr)
        return False


def _write_alert_sheet(path, alerts):
    """Blank labelling sheet: what, when and which frames only, without the model's verdict or reasons."""
    import csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["alert_id", "category", "start_s", "end_s", "frames_to_review", "operator_label", "operator_note"])
        for alert in alerts:
            writer.writerow([
                alert["id"], alert["category"], alert["interval"]["start_us"] / 1e6, alert["interval"]["end_us"] / 1e6,
                " ".join(f"{f['display_index']}@{f['source_time_us'] / 1e6:.2f}s" for f in alert["frames"]), "", "",
            ])


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--archive", type=Path, action="append")
    mode.add_argument("--saved-analysis", type=Path, help="Query a local workflow analysis.json")
    mode.add_argument("--live", action="store_true", help="Analyze new video with Gemini and LangGraph")
    parser.add_argument("--authorize-footage-transfer", action="store_true")
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    parser.add_argument("--max-initial-windows", type=_window_count, default="auto",
                        help=f"Initial scan windows: 'auto' covers the whole video (at most {MAX_INITIAL_WINDOWS}), "
                             f"or 1-{MAX_INITIAL_WINDOWS} (default: auto)")
    parser.add_argument("--window-seconds", type=int, choices=range(1, 11), default=10)
    parser.add_argument("--frame-step-ms", type=int, default=InspectionPlan().frame_step_us // 1000,
                        help="Initial scan step in milliseconds (default: 500). Verification may request 250 ms for a targeted frame inspection.")
    parser.add_argument("--movement-only", action="store_true",
                        help="Run the live baseline without autonomous relational tasks or inspections")
    parser.add_argument("--max-candidates", type=int, default=2, help="Live verification queue limit (default: 2)")
    parser.add_argument("--max-inspections", type=int, default=2, help="Live targeted inspection limit (default: 2)")
    parser.add_argument("--max-agent-calls", type=int, default=6, help="Live logical reasoning call limit (default: 6)")
    parser.add_argument("--max-visible-observations", type=int, default=16,
                        help="Initial observations shown to Investigation before it must search (default: 16)")
    parser.add_argument("--max-verification-iterations", type=int, default=3,
                        help="Live verification decisions per candidate (default: 3)")
    parser.add_argument("--output", type=Path, help="New directory for report and trace")
    parser.add_argument("--interactive", action="store_true", help="Ask questions after analysis")
    parser.add_argument("--question", action="append", default=[], help="Ask after initial analysis")
    args = parser.parse_args(argv)
    if args.saved_analysis:
        if args.output or not (args.question or args.interactive):
            parser.error("--saved-analysis takes --question or --interactive and writes answers to stdout")
        try:
            # These are our own previously generated run artifacts.
            from pydantic import TypeAdapter

            stored = TypeAdapter(Analysis).validate_python(_json(args.saved_analysis)["analysis"])
            source = ingest(args.video)
            if (source.id, source.sha256) != (stored.video.id, stored.video.sha256):
                raise VideoError("Saved analysis does not match the supplied source video")
            analysis = replace(stored, video=source, timeline=_supported_timeline((*stored.timeline, *stored.unresolved)))
            answers = [{"question": q, **asdict(analysis.ask(q))} for q in args.question]
            if answers:
                print(json.dumps(answers, indent=2))
        except (OSError, TypeError, ValueError, KeyError) as exc:
            parser.exit(1, f"{exc}\n")
        if args.interactive:
            _interactive(analysis)
        return 0
    if not args.output:
        parser.error("Video analysis requires --output")
    if args.live and not (args.authorize_footage_transfer and args.authorize_observation_text_transfer):
        parser.error("Live analysis requires explicit authorization for both footage and observation text")
    if args.movement_only and not args.live:
        parser.error("--movement-only applies to live video analysis")
    if args.output.exists():
        parser.error("Output directory already exists")
    if any(args.output.resolve().is_relative_to(root.resolve()) for root in args.archive or ()):
        parser.error("Output must be outside the input archives")
    try:
        metadata = {}
        if args.live:
            from .agents import AgentModels, GeminiDecider, ROLE_HTTP_ATTEMPTS

            plan = InspectionPlan(args.window_seconds * 1_000_000, args.frame_step_ms * 1000)
            windows = args.max_initial_windows
            if windows == "auto":
                windows = initial_window_count(ingest(args.video).duration_us, plan.window_us)
            budget = Budget(
                max_initial_windows=windows, max_candidates=args.max_candidates,
                max_inspections=args.max_inspections, max_agent_calls=args.max_agent_calls,
                max_verification_iterations=args.max_verification_iterations, max_retrievals=1, max_failures=1,
                max_visible_observations=args.max_visible_observations, short_observation_ids=True,
            )
            models = AgentModels.from_env(role_default="gemini-3.6-flash")
            physical_limit = budget.max_agent_calls * ROLE_HTTP_ATTEMPTS
            media_limit = budget.max_initial_windows + budget.max_inspections
            decide = GeminiDecider.from_env(
                authorized=True, models=models, max_physical_requests=physical_limit,
                max_physical_media_requests=media_limit,
            )
            with decide.adapter.client:
                analysis = analyze_video(
                    args.video, decide.adapter, budget=budget, plan=plan, decide=decide, controller="langgraph",
                    movement_only=args.movement_only,
                )
            metadata = {
                "media_attempts": decide.http_budget.media_attempts,
                "physical_requests": decide.http_budget.sent + len(decide.http_budget.media_attempts),
                "models": asdict(models), "role_calls": decide.calls,
                "independent_relational_tasks": not args.movement_only,
                "max_physical_role_requests": physical_limit,
                "max_physical_media_requests": media_limit,
                "max_physical_requests": physical_limit + media_limit,
            }
        else:
            analysis = analyze_archive(args.video, args.archive)
        args.output.mkdir(mode=0o700)
        (args.output / "report.md").write_text(analysis.report, encoding="utf-8")
        result = {**metadata, "analysis": asdict(analysis), "answers": [
            {"question": question, **asdict(analysis.ask(question, inspect_missing=True))} for question in args.question
        ]}
        (args.output / "analysis.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if analysis.review is not None:
            _write_alert_sheet(args.output / "alerts.csv", analysis.review["alerts"])
        _write_guard_report_safely(args.output, result)
    except (VideoError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
    print(analysis.report, end="")
    for answer in result["answers"]:
        print(f"\n{answer['question']}\n{answer['text']}")
    if args.interactive:
        _interactive(analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
