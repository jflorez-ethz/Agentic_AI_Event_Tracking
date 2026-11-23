"""Paired archive-only evaluation of Gemini role decisions and the baseline."""

import argparse
from collections import Counter
from dataclasses import asdict, replace
import json
from pathlib import Path
import time

from .agents import AgentModels, GeminiDecider, ROLE_HTTP_ATTEMPTS
from .contracts import VideoError
from .video import ingest
from .workflow import EVENT_LABELS, Budget, _analyze_archive_snapshot, _load_archive

EVAL_BUDGET = Budget(
    max_archive_attempts=7, max_candidates=2, max_retrievals=1, max_inspections=2,
    max_initial_windows=0, max_agent_calls=6, max_verification_iterations=2, max_failures=1,
)


def _metrics(analysis, calls, elapsed_ms):
    actions = Counter(event.action for event in analysis.trace)
    usage = Counter()
    for call in calls:
        usage.update(call["usage"])
    evidence = {
        (f.observation.id, f.citation)
        for entry in analysis.evidence for f in entry.findings
    }
    events = analysis.timeline + analysis.unresolved
    citations = sum(len(e.citations) for e in events)
    invalid = [
        event.observation_ids for event in events
        if len(event.observation_ids) != len(event.citations)
        or any(
            (identifier, citation) not in evidence or citation.video_id != analysis.video.id
            for identifier, citation in zip(event.observation_ids, event.citations)
        )
    ]
    # Reference rates recorded in the E1 preflight, not a billing receipt.
    accounted = [
        c["usage"] for c in calls if c["model"] == "gemini-3.5-flash-lite"
        and {"prompt_token_count", "candidates_token_count"} <= c["usage"].keys()
    ]
    priced = sum(
        (0.30 * u["prompt_token_count"]
         + 2.50 * (u["candidates_token_count"] + u.get("thoughts_token_count", 0))) / 1_000_000
        for u in accounted
    )
    return {
        "elapsed_ms": elapsed_ms,
        "placement_count": sum(e.category == "object_placed" for e in analysis.timeline),
        "unresolved_count": len(analysis.unresolved),
        "ambiguous_handling_retained": any(e.category == "insufficient_evidence" for e in analysis.unresolved),
        "abandonment_query_has_supported_event": bool(analysis.ask("Was the object abandoned?").events),
        "citation_count": citations, "invalid_citation_events": invalid,
        "model_calls": len(calls), "tokens": dict(usage),
        "physical_http_attempts": (
            sum(len(c["transport_attempts"]) for c in calls)
            if all("transport_attempts" in c for c in calls) else None
        ),
        "calls_with_usage": sum(bool(c["usage"]) for c in calls),
        "priced_calls": len(accounted),
        "partial_reference_cost_usd": round(priced, 8) if accounted else None,
        "model_elapsed_ms": sum(c["elapsed_ms"] for c in calls),
        "tool_calls": actions["search"] + actions["inspect"],
        "action_counts": dict(actions),
    }


class ScriptedRecovery:
    """Offline fixture that repeats the premature verdict from the saved evaluation."""

    def __init__(self):
        self.calls = []

    def __call__(self, role, context):
        self.calls.append({"role": role, "model": "scripted", "status": "fixture", "usage": {}, "elapsed_ms": 0})
        if role == "investigation":
            ids = [
                identifier for identifier, evidence in context["evidence"].items()
                if evidence["category"] in EVENT_LABELS or evidence["category"] == "insufficient_evidence"
            ]
            selected = ids[:context["max_candidates"]]
            return {
                "action": "delegate", "ids": selected, "reason": "Delegate observable events and uncertainty.",
                "dispositions": [
                    {"id": identifier, "status": "deferred", "reason": "Outside this scripted verification queue."}
                    for identifier in context["evidence"] if identifier not in selected
                ],
            }
        if role == "reporting":
            lead = next((f["id"] for f in context["findings"] if f["verdict"] == "supported"), None)
            return {"action": "report", "lead_id": lead, "emphasis": "uncertainty",
                    "reason": "Select a supported lead and retain unresolved findings."}

        seed = context["candidate_id"]
        candidate = context["evidence"][seed]
        feedback = context.get("validation_feedback")
        if candidate["category"] == "insufficient_evidence":
            verdict, ids = "insufficient", [seed]
        elif feedback and context["last_tool_result"] is None:
            modality = "clip" if candidate["modality"] == "frames" else "frames"
            return {"action": "inspect", "modality": modality, **candidate["interval"],
                    "reason": "Check a complementary inspection overlapping the cited interval."}
        elif feedback:
            pairs = []
            for identifier, other in context["evidence"].items():
                common = sorted(set(candidate["frame_ids"]) & set(other["frame_ids"]))
                if (other["category"] == candidate["category"] and common
                        and other["inspection_id"] != candidate["inspection_id"]):
                    pairs.append({
                        "id": identifier, "status": "same_event",
                        "seed_quote": candidate["description"], "other_quote": other["description"],
                        "shared_frame_id": common[0],
                    })
            return {
                "action": "verdict", "verdict": "supported" if pairs else "insufficient",
                "ids": [seed, *(pair["id"] for pair in pairs)], "correspondence": pairs,
                "reason": "Offline fixture assessment using the archived descriptions and shared frame.",
            }
        else:
            verdict, ids = "supported", [seed]
        return {"action": "verdict", "verdict": verdict, "ids": ids, "correspondence": [],
                "reason": "Assess the currently visible evidence."}


def evaluate_archive(source, archives, *, decide=None, controller="python", scripted_recovery=False):
    video = ingest(source)
    graph_enabled = controller == "langgraph" or scripted_recovery
    budget = replace(EVAL_BUDGET, max_verification_iterations=3) if graph_enabled else EVAL_BUDGET
    evidence = _load_archive(video, archives, budget)
    if len(evidence) != budget.max_archive_attempts:
        raise VideoError("Controlled E1 evaluation requires the seven comparison and retry attempts")
    result = {
        "schema_version": 1, "budget": asdict(budget), "evaluation": {}, "role_calls": [],
        "cost_basis": "E1 preflight standard paid reference rates, no cache discounts or billing verification",
    }
    modes = [("baseline", None, "python")]
    if scripted_recovery:
        if decide is not None:
            raise VideoError("Scripted recovery cannot use a hosted decision callable")
        modes.extend((
            ("python_scripted", ScriptedRecovery(), "python"),
            ("langgraph_scripted", ScriptedRecovery(), "langgraph"),
        ))
        result["scripted_role_calls"] = {}
    elif decide is not None:
        modes.append(("gemini", decide, controller))
    for name, decision, engine in modes:
        started = time.monotonic()
        # This entry point has no observation provider. All tools read this local snapshot.
        call_offset = len(decision.calls) if decision is not None else 0
        analysis = _analyze_archive_snapshot(video, evidence, budget, decide=decision, controller=engine)
        elapsed = round((time.monotonic() - started) * 1000)
        calls = decision.calls[call_offset:] if decision is not None else []
        result.setdefault("controllers", {})[name] = engine
        result[name] = asdict(analysis)
        result["evaluation"][name] = _metrics(analysis, calls, elapsed)
        if name == "gemini":
            result["role_calls"] = calls
            result["models"] = asdict(decide.models)
            if decide.http_budget is not None:
                result["transport_policy"] = {
                    "sdk_version": decide.adapter.sdk_version,
                    "max_attempts_per_call": ROLE_HTTP_ATTEMPTS,
                    "max_physical_requests": decide.http_budget.limit,
                }
        elif decision is not None:
            result["scripted_role_calls"][name] = calls
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True, help="New local output directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Evaluate Gemini text decisions")
    mode.add_argument("--scripted-recovery", action="store_true", help="Compare both controllers without network calls")
    parser.add_argument("--controller", choices=("python", "langgraph"), default="python",
                        help="Controller for the authorized Gemini mode")
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.authorize_observation_text_transfer:
        parser.error("Live evaluation requires explicit observation-text transfer authorization")
    if any(args.output.resolve().is_relative_to(root.resolve()) for root in args.archive):
        parser.error("Output must be outside input archives")
    if args.output.exists():
        parser.error("Output directory already exists")
    try:
        decide = GeminiDecider.from_env(
            authorized=True, models=AgentModels.from_env(),
            max_physical_requests=EVAL_BUDGET.max_agent_calls * ROLE_HTTP_ATTEMPTS,
        ) if args.live else None
        args.output.mkdir(mode=0o700)
        result = evaluate_archive(
            args.video, args.archive, decide=decide, controller=args.controller,
            scripted_recovery=args.scripted_recovery,
        )
        for mode in result["evaluation"]:
            if mode in result:
                (args.output / f"{mode}-report.md").write_text(result[mode]["report"], encoding="utf-8")
        (args.output / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result["evaluation"], indent=2))
    except (VideoError, OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
