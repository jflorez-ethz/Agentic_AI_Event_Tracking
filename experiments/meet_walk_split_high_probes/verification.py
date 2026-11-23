"""Evaluate Verification on the fixed Meet Walk Split Investigation handoff."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from probe import CONTINUATION_RECORD, MODEL, SOURCE, archived_search, restore, save
from security_augmented.agents import AgentModels, AgentRun, GeminiDecider, ROLE_HTTP_ATTEMPTS, RoleHTTPBudget
from security_augmented.contracts import VideoError
from security_augmented.gemini import GeminiAdapter
from security_augmented.graph_workflow import require_graph, run_graph
from security_augmented.relations import review_from_dict, validate_review
from security_augmented.video import _decode, ingest
from security_augmented.workflow import Analysis, Budget, InspectionPlan, _observe_video

HANDOFF = Path(__file__).with_name("live.CIW3cs") / "continuation"


def load_reviews(path, video, initial, plan):
    if plan.frame_step_us != 500_000:
        raise VideoError("Relational replay expects a 500 ms archived scan")
    document = json.loads(path.read_text())
    if document["source_sha256"] != video.sha256:
        raise VideoError("Review file references a different source")
    reviews = {identifier: review_from_dict(row) for identifier, row in document["reviews"].items()}
    known = {frame.id: frame for f in initial for frame in f.citation.frames}
    for review in reviews.values():
        validate_review(review, known, known, (video.width, video.height))
    frames = {known[view.frame_id].display_index: known[view.frame_id]
              for review in reviews.values() for view in review.views}
    indices = tuple(sorted(frames))
    for index, rgb in zip(indices, _decode(video, indices) if indices else (), strict=True):
        frame = frames[index]
        if (video.frame_pts[index] != frame.pts
                or video.time_at_pts(frame.pts) * 1_000_000 != frame.source_time_us
                or hashlib.sha256(rgb).hexdigest() != frame.rgb24_sha256):
            raise VideoError("A reviewed frame differs from its source provenance")
    return reviews


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-footage-transfer", action="store_true")
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    relational = parser.add_mutually_exclusive_group()
    relational.add_argument("--relational-reviews", type=Path, help="Opt-in JSON file of local visual review records")
    relational.add_argument("--autonomous-relations", action="store_true",
                            help="Allow targeted frame calls to propose relations without a review file")
    parser.add_argument("--relational-selection", action="store_true",
                        help="Offer overlapping archived observations and a question-bearing relational inspection")
    parser.add_argument("--relational-tasks", action="store_true",
                        help="Let live Investigation assign independent relational tasks over the archived scan")
    parser.add_argument("--question", action="append", default=[])
    args = parser.parse_args(argv)
    if args.relational_tasks and not args.autonomous_relations:
        parser.error("--relational-tasks requires --autonomous-relations")
    if args.relational_selection and not args.autonomous_relations:
        parser.error("--relational-selection requires --autonomous-relations")
    if not (args.authorize_footage_transfer and args.authorize_observation_text_transfer):
        parser.error("Explicit authorization for targeted footage and observation text is required")
    require_graph()
    archived = json.loads(CONTINUATION_RECORD.read_text())["analysis"]
    decision = json.loads((HANDOFF / "decision.json").read_text())
    accepted = json.loads((HANDOFF / "result.json").read_text())
    context = json.loads((HANDOFF / "input.json").read_text())["context"]
    if (accepted["status"] != "valid_delegation" or accepted["validation"] != "passed"
            or json.loads(accepted["raw_response"]) != decision or accepted["delegated"] != decision["ids"]):
        raise VideoError("Archived decision does not match the accepted handoff")
    video = ingest(SOURCE)
    if video.sha256 != archived["video"]["sha256"]:
        raise VideoError("Source differs from archived scan")
    initial = restore(archived)
    budget = Budget(**archived["budget"])
    plan = InspectionPlan(**archived["coverage"]["plan"])
    if args.autonomous_relations and plan.frame_step_us != 500_000:
        raise VideoError("Autonomous relational replay requires the archived 500 ms scan")
    reviews = load_reviews(args.relational_reviews, video, initial, plan) if args.relational_reviews else {}
    search = archived_search(archived)
    replayed_calls = 0 if args.relational_tasks else 2
    role_budget = RoleHTTPBudget((budget.max_agent_calls - replayed_calls) * ROLE_HTTP_ATTEMPTS)
    media_budget = RoleHTTPBudget(budget.max_inspections)
    targeted, media_attempts, trace, decisions = [], [], [], []
    models = AgentModels(video=MODEL, investigation=MODEL, verification=MODEL, reporting=MODEL)
    args.output.mkdir(mode=0o700)

    def active_transport():
        return role_budget if role_budget.attempts is not None else media_budget

    adapter = GeminiAdapter.from_env(
        authorized=True, model=models.video, single_request=True,
        client_args={"follow_redirects": False, "event_hooks": {
            "request": [lambda request: active_transport().before_send(request)],
            "response": [lambda response: active_transport().after_response(response)],
        }},
    )
    decide = GeminiDecider(adapter, models, http_budget=role_budget)

    def replay_or_decide(role, current):
        if role == "investigation" and not args.relational_tasks:
            if current["last_tool_result"] is None:
                return {"action": "search", **search["interval"], "reason": "Replay the archived local search."}
            if current != context:
                raise VideoError("Reconstructed Investigation context differs from the accepted handoff")
            return decision
        if not args.relational_tasks and run.dispositions != {row["id"]: row for row in accepted["dispositions"]}:
            raise VideoError("Replayed dispositions differ from the accepted handoff")
        action = decide(role, current)
        decisions.append({"role": role, "candidate_id": current.get("candidate_id"), "decision": action,
                          **({"context": current} if (args.relational_tasks or
                                                      role == "verification" and args.relational_selection) else {})})
        return action

    def inspect(interval, modality, *, relational=False, visual_question=None):
        media_budget.attempts = []
        try:
            entry = _observe_video(video, adapter, interval, modality, "targeted", plan, model_guided=True,
                                   relational=relational, visual_question=visual_question)
        finally:
            media_attempts.extend(media_budget.attempts)
            media_budget.attempts = None
        targeted.append(entry)
        return (entry,)

    run = AgentRun(video, replay_or_decide, inspect, budget, trace, initial_scan=archived["completion"]["initial_scan"],
                   relation_reviews=reviews, autonomous_relations=args.autonomous_relations,
                   relational_selection=args.relational_selection, relational_tasks=args.relational_tasks)
    with adapter.client:
        events, report = run_graph(run, initial)
    (args.output / "report.md").write_text(report, encoding="utf-8")
    analysis = Analysis(video, tuple(targeted), initial, tuple(e for e in events if e.verdict == "supported"),
                        tuple(e for e in events if e.verdict != "supported"), tuple(trace), report, budget)
    save(args.output, "result.json", {
        "autonomous_relations": args.autonomous_relations,
        "relational_selection": args.relational_selection,
        **({"independent_relational_tasks": True} if args.relational_tasks else {}),
        "relational_reviews": {identifier: asdict(review) for identifier, review in reviews.items()},
        "answers": [{"question": question, **asdict(analysis.ask(question))} for question in args.question],
        "source_sha256": video.sha256, "archived_scan": str(CONTINUATION_RECORD), "archived_handoff": str(HANDOFF),
        "models": asdict(models), "budget": asdict(budget), "plan": asdict(plan),
        "max_physical_role_requests": role_budget.limit, "max_physical_media_requests": media_budget.limit,
        "physical_requests": role_budget.sent + media_budget.sent, "media_attempts": media_attempts,
        "role_calls": decide.calls, "decisions": decisions, "targeted_evidence": [asdict(entry) for entry in targeted],
        "events": [asdict(event) for event in events], "completion": run.completion(),
        "trace": [asdict(row) for row in trace],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
