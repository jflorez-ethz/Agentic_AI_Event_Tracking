"""Replay one failed stage without running the video-first workflow."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from security_augmented.agents import (
    INVESTIGATION_MAX_OUTPUT_TOKENS, INVESTIGATION_THINKING_LEVEL,
    AgentModels, AgentRun, GeminiDecider, RoleHTTPBudget, _decision_schema,
)
from security_augmented.contracts import FrameEvidence, Interval, VideoError
from security_augmented.gemini import GeminiAdapter, GeminiFailure
from security_augmented.observation import FrameReference, FrameSequenceInput, Observation, ObservationRequest
from security_augmented.video import _decode, ingest, sample
from security_augmented.workflow import Budget, Citation, EVENT_LABELS, Finding

CONTINUATION_RECORD = Path("experiments/meet_walk_split_high.uGljGL/run/analysis.json")
INVESTIGATION_RECORD = Path("experiments/meet_walk_split_high.Cpby7p/run/analysis.json")
RECORD = Path("experiments/meet_walk_split_high.Lgrgbb/run/analysis.json")
SOURCE = Path("data/raw/Meet_WalkSplit_pts.mp4")
MODEL = "gemini-3.6-flash"
# Snapshot of the live model-guided observation request prompt used by the archived run.
PROMPT = (
    "Describe visible activities. Use placement, removal or entry only when the "
    "observable transition is established. Describe uncertain action as insufficient evidence. "
    "Cite the supporting visual evidence. Do not infer ownership, intent or abandonment."
    " Use object_appeared or object_disappeared for visibility changes without an observed "
    "physical action. Describe the visible before and after states and cite frames for both. "
    "Use object_placed or object_removed only when the physical action itself is visible."
    " Use person_appeared for first visibility and person_moved for motion already within view. "
    "Use person_enters_area only when a person visibly crosses an identifiable physical boundary. "
    "Name the boundary and describe the crossing in the observation. The image edge only marks visibility."
)


def save(output, name, payload):
    (output / name).write_text(json.dumps(payload, indent=2) + "\n")


def media_input(video, analysis, adapter):
    original = next(e["inspection"] for e in analysis["evidence"] if e["interval"]["start_us"] == 10_000_000)
    window = Interval(**original["requested_interval"])
    inspection = sample(video, window, original["requested_times_us"])
    replayed = json.loads(json.dumps(asdict(inspection)))
    for key, value in original.items():
        if key != "extraction_version" and replayed.get(key) != value:
            raise VideoError(f"Replay differs from archived inspection: {key}")
    pixels = _decode(video, tuple(f.display_index for f in inspection.frames))
    media = FrameSequenceInput(inspection, video.width, video.height, pixels)
    prepared = adapter.prepare(ObservationRequest(media, (*EVENT_LABELS, "insufficient_evidence"), PROMPT))
    settings = prepared.config
    if (adapter.model != MODEL or settings["max_output_tokens"] != 8192
            or settings["thinking_config"] != {"thinking_level": "HIGH"} or not prepared.single_request):
        raise VideoError("Expected Gemini 3.6 Flash, HIGH thinking, an 8192-token ceiling and a single request")
    return prepared


def restore(analysis):
    findings = []
    for row in analysis["observations"]:
        o, c = row["observation"], row["citation"]
        frames = tuple(FrameEvidence(**f) for f in c["frames"])
        obs = Observation(o["id"], o["inspection_id"], o["category"], o["description"],
                          FrameReference(tuple(o["evidence"]["frame_ids"])), o["visibility_limits"], o["uncertainty"])
        findings.append(Finding(obs, Citation(c["video_id"], c["inspection_id"], c["modality"],
                                              Interval(**c["interval"]), frames)))
    if len(findings) != 11:
        raise VideoError("Expected eleven archived observations")
    return tuple(findings)


def archived_search(analysis):
    trace = [row for row in analysis["trace"] if row["actor"] == "investigation"]
    search, = [row["details"] for row in trace if row["action"] == "search"]
    result, = [row["details"] for row in trace if row["action"] == "tool_result"]
    return {"interval": search, "result": result}


class ProbeDecider(GeminiDecider):
    """Capture the raw candidate while using the production parse and completion checks."""

    raw_response = None

    def _request(self, call, **kwargs):
        response = super()._request(call, **kwargs)
        self.raw_response = response.text
        return response


def investigate(video, findings, budget, decide, output, *, search=None):
    payloads = []

    def call(role, context):
        if role != "investigation" or payloads:
            raise VideoError("Probe permits one Investigation decision")
        payloads.append(context)
        save(output, "input.json", {
            "model": MODEL, "thinking_level": INVESTIGATION_THINKING_LEVEL,
            "max_output_tokens": INVESTIGATION_MAX_OUTPUT_TOKENS,
            "budget": asdict(budget), "observation_ids": list(context["evidence"]), "context": context,
            **({"archived_search": search} if search is not None else {}),
            "schema": _decision_schema(role, context),
        })
        if decide is None:
            raise VideoError("Offline plan")
        action = decide(role, context)
        save(output, "decision.json", action)
        return action

    trace = []
    agent = AgentRun(video, call, lambda *_: (), budget, trace)
    if search is None:
        picks = agent.investigate(findings)
    else:
        agent.initial = {finding.observation.id: finding for finding in findings}
        visible = dict(list(agent.initial.items())[:max(8, budget.max_candidates)])
        tool_result = search["result"]
        added = tool_result["ids"]
        interval = Interval(**search["interval"])
        interval.validate(video.duration_us)
        if (tool_result["status"] != "found" or added != list(agent.initial)[len(visible):]
                or any(not (agent.initial[i].citation.interval.start_us < interval.end_us
                            and interval.start_us < agent.initial[i].citation.interval.end_us) for i in added)):
            raise VideoError("Search trace does not account for the archived continuation evidence")
        visible.update((identifier, agent.initial[identifier]) for identifier in added)
        agent.retrievals = 1
        agent.seen_tools.add(("search", interval))
        agent.remaining -= 1
        picks = agent._investigate_visible(visible, tool_result)
    if decide is not None:
        accepted = any(d.action == "delegate" for d in trace)
        rejected = any(d.action == "rejected" for d in trace)
        return {"status": "valid_delegation" if accepted else "failed",
                "validation": "passed" if accepted else "failed" if rejected else "not_reached",
                "dispositions": list(agent.dispositions.values()),
                "delegated": [f.observation.id for f in picks], "raw_response": decide.raw_response,
                "calls": decide.calls, "trace": [asdict(d) for d in trace]}
    return None


def run_media(adapter, prepared):
    try:
        result = adapter.infer_prepared(prepared)
    except GeminiFailure as exc:
        return {"status": "failed", "validation": "failed" if exc.stage == "validation" else "not_reached",
                "stage": exc.stage, "error": str(exc), "completion": exc.diagnostics,
                "metadata": asdict(exc.metadata), "raw_response": exc.raw_response,
                "provider_usage": (exc.response_details or {}).get("usage_metadata")}
    details = result.response_details or {}
    candidates = details.get("candidates", [])
    return {"status": "success", "validation": "passed", "metadata": asdict(result.metadata),
            "completion": {"candidate_count": len(candidates),
                           "finish_reasons": [c.get("finish_reason") for c in candidates]},
            "observations": [asdict(o) for o in result.observations],
            "raw_response": result.raw_response, "provider_usage": details.get("usage_metadata")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", choices=("media", "investigation", "continuation"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--authorize-footage-transfer", action="store_true")
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    args = parser.parse_args(argv)
    authorized = (args.authorize_footage_transfer if args.probe == "media"
                  else args.authorize_observation_text_transfer)
    if args.live and not authorized:
        parser.error("Live probe requires explicit authorization for its transfer type")
    record = {"media": RECORD, "investigation": INVESTIGATION_RECORD, "continuation": CONTINUATION_RECORD}[args.probe]
    analysis = json.loads(record.read_text())["analysis"]
    video = ingest(SOURCE)
    if video.sha256 != analysis["video"]["sha256"]:
        raise VideoError("Source differs from the archived run")
    args.output.mkdir(mode=0o700)
    prepared = None
    search = archived_search(analysis) if args.probe == "continuation" else None
    if args.probe == "media":
        prepared = media_input(video, analysis, GeminiAdapter(model=MODEL, single_request=True))
        save(args.output, "input.json", {"model": MODEL, "config": prepared.config,
                                        "single_request": True, "inspection": prepared.media_map,
                                        "text_parts": [p["text"] for p in prepared.contents[0]["parts"] if "text" in p],
                                        "png_sha256": [hashlib.sha256(p["inline_data"]["data"]).hexdigest()
                                                       for p in prepared.contents[0]["parts"] if "inline_data" in p]})
    else:
        findings = restore(analysis)
        budget = Budget(**analysis["budget"])
        if not args.live:
            investigate(video, findings, budget, None, args.output, search=search)
    if not args.live:
        return 0

    transport = RoleHTTPBudget(1)
    transport.attempts = []
    adapter = GeminiAdapter.from_env(authorized=True, model=MODEL, single_request=True, client_args={
        "follow_redirects": False,
        "event_hooks": {"request": [transport.before_send], "response": [transport.after_response]},
    })
    with adapter.client:
        if prepared is not None:
            result = run_media(adapter, prepared)
        else:
            # No decider-level retry wrapper. The independent pre-send cap counts both paths.
            decide = ProbeDecider(adapter, AgentModels(investigation=MODEL, video=MODEL))
            result = investigate(video, findings, budget, decide, args.output, search=search)
    result["transport_attempts"] = transport.attempts
    completion = result.get("completion")
    if completion and "candidate_count" in completion:
        result["normally_completed"] = completion["candidate_count"] == 1 and completion["finish_reasons"] == ["STOP"]
    save(args.output, "result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
