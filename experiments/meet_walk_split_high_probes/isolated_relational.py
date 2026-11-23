"""Freeze and run one isolated selection or perception request for the archived candidate."""
import argparse
import base64
from dataclasses import asdict
from importlib.metadata import version
import json
from pathlib import Path
from types import SimpleNamespace

from probe import SOURCE, ProbeDecider, restore, save
from sampling_pair import sha
from security_augmented.agents import AgentModels, AgentRun, InspectionRejected, RoleHTTPBudget
from security_augmented.contracts import Interval, VideoError
from security_augmented.gemini import MAX_INLINE_BYTES, GeminiAdapter, GeminiFailure
from security_augmented.relations import validate_review
from security_augmented.video import ingest
from security_augmented.workflow import Budget, InspectionPlan, _observe_video

ARCHIVE = Path(__file__).with_name("verification-relational-selection-live") / "result.json"
CANDIDATE = "observation-ac83682fb5f7d3d5ee5c7eeacb15a97e8a0854d2a629f67175c20d78061d5390"
WINDOW = Interval(10_000_000, 13_000_001)
KINDS = ("verification", "perception")


def load_inputs():
    archive = json.loads(ARCHIVE.read_text())
    row, = [row for row in archive["decisions"] if row["candidate_id"] == CANDIDATE]
    prior = json.loads(Path(archive["archived_scan"]).read_text())["analysis"]
    video = ingest(SOURCE)
    plan = InspectionPlan(**archive["plan"])
    sdk_version = dict(archive["targeted_evidence"][0]["inference"]["settings"])["sdk_version"]
    if (video.sha256 != archive["source_sha256"] or plan.frame_step_us != 500_000
            or sdk_version != version("google-genai")):
        raise VideoError("Source, frame step or SDK differs from the archived run")
    return video, plan, archive, row, restore(prior)


def decision_audit(run, seed, context, action, dispatches):
    if action is None:
        return {"status": "decision_rejected"}
    if action["action"] == "inspect":
        if not context["can_inspect_and_reconsider"]:
            return {"status": "inspection_rejected", "code": "cannot_inspect_and_reconsider"}
        try:
            run.reinspect(seed, action, run.visible_for(seed))
        except InspectionRejected as exc:
            return {"status": "inspection_rejected", "code": exc.code, "reason": str(exc)}
        if len(dispatches) != 1:
            raise VideoError("Expected one local dispatch check")
        return {"status": "relational_inspection_eligible" if action.get("relational") else "ordinary_inspection_eligible",
                "interval": asdict(dispatches[0]), "visual_question": action.get("visual_question"),
                "evidence_gap": action["reason"], "inspection_executed": False}
    try:
        _, verdict, *_ = run.verdict(seed, action, run.visible_for(seed))
    except VideoError as exc:
        return {"status": "verdict_rejected", "reason": str(exc)}
    return {"status": "unresolved" if verdict == "insufficient" else "movement_verdict", "verdict": verdict}


def selection(inputs, adapter, http_budget):
    video, _, archive, row, initial = inputs
    models = AgentModels(**archive["models"])
    decider = ProbeDecider(adapter, models, http_budget=http_budget)
    context = row["context"]
    dispatches, trace = [], []

    def stop_at_dispatch(interval, modality, **kwargs):
        dispatches.append(interval)
        return ()

    run = AgentRun(video, decider, stop_at_dispatch, Budget(**archive["budget"]), trace,
                   autonomous_relations=True, relational_selection=True)
    run.initial = {f.observation.id: f for f in initial}
    run.dispositions = {d["id"]: d for d in archive["completion"]["observation_dispositions"]}
    seed = run.initial[CANDIDATE]
    run.remaining = context["remaining_model_calls"] + 1
    run.inspections = run.budget.max_inspections - context["remaining_inspections"]
    # This candidate had no previous actions. Restore the tool keys accepted
    # before its decision, excluding rejected inspections.
    earlier = archive["decisions"][:archive["decisions"].index(row)]
    requested = {(d["candidate_id"], d["decision"].get("modality"),
                  d["decision"].get("start_us"), d["decision"].get("end_us"))
                 for d in earlier if d["decision"]["action"] == "inspect"}
    for entry in archive["trace"]:
        if entry["action"] == "inspect":
            details = entry["details"]
            if (entry["observation_ids"][0], details["modality"], details["start_us"],
                    details["end_us"]) in requested:
                run.seen_tools.add((details["modality"], Interval(details["start_us"], details["end_us"])))
    if len(run.seen_tools) != run.inspections or set(run.visible_for(seed)) != context["evidence"].keys():
        raise VideoError("Archived dispatch state could not be reconstructed")

    action = run.action("verification", context)
    return {"status": "received" if action else "failed", "decision": action,
            "raw_response": decider.raw_response, "role_call": decider.calls[0],
            "decision_audit": decision_audit(run, seed, context, action, dispatches),
            "physical_http_requests": http_budget.sent}


def perception(inputs, adapter, http_budget):
    video, plan, *_ = inputs
    details = {}
    rejected_response = None

    def infer(request):
        nonlocal rejected_response
        try:
            result = adapter.infer(request)
        except GeminiFailure as exc:
            rejected_response = exc.raw_response
            details.update(exc.response_details or {})
            raise
        details.update(result.response_details or {})
        return result

    http_budget.attempts = []
    entry = _observe_video(video, SimpleNamespace(infer=infer), WINDOW, "frames", "targeted", plan,
                           model_guided=True, relational=True)
    check = None
    if entry.relation is not None:
        frames = {f.id: f for f in entry.inspection.frames}
        check = validate_review(entry.relation, frames, frames, (video.width, video.height))
    no_proposal = "abstained"
    if entry.status == "success" and entry.relational_raw_response:
        if "relation" not in json.loads(entry.relational_raw_response):
            no_proposal = "no_proposal"
    return {"status": entry.status, "inspection": asdict(entry.inspection) if entry.inspection else None,
            "entry": asdict(entry), "raw_response": entry.relational_raw_response or rejected_response,
            "completion": entry.failure_diagnostics or {
                "candidate_count": len(details.get("candidates", [])),
                "finish_reasons": [c.get("finish_reason") for c in details.get("candidates", [])],
            },
            "proposal_status": (check.status if check else "invalid" if entry.relation_error
                                else no_proposal if entry.status == "success" else "not_reached"),
            "relation_validation": asdict(check) if check else None,
            "transport_attempts": http_budget.attempts, "physical_http_requests": http_budget.sent}


def execute(kind, inputs, adapter, http_budget):
    handler = selection if kind == "verification" else perception
    return handler(inputs, adapter, http_budget)


def request_path(kind, inputs):
    return f"/v1beta/models/{inputs[2]['models']['video' if kind == 'perception' else kind]}:generateContent"


def fingerprint(kind, inputs):
    import httpx
    from google import genai
    from google.genai import types

    archive, row = inputs[2:4]
    budget = RoleHTTPBudget(1)
    captures = []
    recorded_call = archive["role_calls"][archive["decisions"].index(row)]

    def capture(request):
        if request.url.path != request_path(kind, inputs):
            raise VideoError("Unexpected SDK request path")
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        images = []
        for part in parts:
            if "inlineData" in part:
                encoded = part["inlineData"]["data"]
                decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                images.append({"bytes": len(decoded), "sha256": sha(decoded)})
                part["inlineData"]["data"] = "<image omitted>"
        if kind == "verification":
            config = body["generationConfig"]
            if (config["maxOutputTokens"] != recorded_call["max_output_tokens"]
                    or config["thinkingConfig"]["thinking_level"] != recorded_call["thinking_level"]):
                raise VideoError("Verification generation settings differ from the archive")
            if images or json.loads(parts[0]["text"]) != row["context"]:
                raise VideoError("Serialized Verification context differs from the archive")
        wire = request.content
        if len(wire) > MAX_INLINE_BYTES:
            raise VideoError("Serialized request exceeds the inline ceiling")
        captures.append({"wire_bytes": len(wire), "wire_sha256": sha(wire),
                         "body_without_images": body, "images": images})
        answer = row["decision"] if kind == "verification" else {"observations": [], "relation": None}
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]},
        }]})

    with genai.Client(api_key="local-mock-only", vertexai=False, http_options=types.HttpOptions(
        api_version="v1beta", timeout=90_000, retry_options=types.HttpRetryOptions(attempts=1),
        client_args={"transport": httpx.MockTransport(capture), "follow_redirects": False, "event_hooks": {
            "request": [budget.before_send], "response": [budget.after_response],
        }},
    )) as client:
        result = execute(kind, inputs, GeminiAdapter(client=client, model=archive["models"]["video"],
                                                     single_request=True), budget)
    record, = captures
    if result["physical_http_requests"] != 1 or result["status"] == "failed":
        raise VideoError("Mock did not complete the isolated request")
    return {"kind": kind, "source_sha256": inputs[0].sha256, "sdk_version": version("google-genai"),
            **record, **({"archived_context": row["context"], "archived_decision": row["decision"],
                         "archived_role_call": recorded_call}
                         if kind == "verification" else {"inspection": result["inspection"]})}


def main(argv=None):
    import os
    from unittest.mock import patch

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prepare = subparsers.add_parser("prepare", allow_abbrev=False)
    prepare.add_argument("--output", type=Path, required=True)
    run = subparsers.add_parser("run", allow_abbrev=False)
    run.add_argument("kind", choices=KINDS)
    run.add_argument("--prepared", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--authorize-observation-text-transfer", action="store_true")
    run.add_argument("--authorize-footage-transfer", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "run" and not (args.authorize_observation_text_transfer if args.kind == "verification"
                                   else args.authorize_footage_transfer):
        parser.error("Explicit authorization for this probe's data transfer is required")
    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        inputs = load_inputs()
        if args.mode == "prepare":
            args.output.mkdir(mode=0o700)
            for kind in KINDS:
                save(args.output, f"{kind}.json", fingerprint(kind, inputs))
            return 0
        expected = json.loads((args.prepared / f"{args.kind}.json").read_text())
        if json.loads(json.dumps(fingerprint(args.kind, inputs))) != expected:
            raise VideoError("The reconstructed request differs from the frozen plan")

        budget = RoleHTTPBudget(1)

        def before_send(request):
            if request.url.path != request_path(args.kind, inputs) or sha(request.content) != expected["wire_sha256"]:
                raise VideoError("Outbound request differs from the frozen plan")
            budget.before_send(request)

        args.output.mkdir(mode=0o700)
        save(args.output, "input.json", expected)
        adapter = GeminiAdapter.from_env(
            authorized=True, model=inputs[2]["models"]["video"], single_request=True,
            client_args={"follow_redirects": False, "event_hooks": {
                "request": [before_send], "response": [budget.after_response],
            }},
        )
        with adapter.client:
            result = execute(args.kind, inputs, adapter, budget)
        save(args.output, "result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
