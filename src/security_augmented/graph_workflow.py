"""Optional StateGraph routing for the existing evidence-controlled agent roles."""

from dataclasses import asdict
from typing import NotRequired, TypedDict

from .agents import AgentRun, InspectionRejected, MAX_INSPECTION_SPAN_US, RelationalTask
from .evidence import CorroborationRequired
from .contracts import Interval, VideoError
from .workflow import Event, Finding, RelationalFinding


class ValidationFeedback(TypedDict):
    code: str
    reason: str
    candidate_id: str
    remaining_recoveries: int
    requested: NotRequired[dict]
    constraints: NotRequired[dict]


class GraphState(TypedDict, total=False):
    initial: tuple[Finding, ...]
    pending: tuple[Finding | RelationalTask, ...]
    task: RelationalTask | None
    task_findings: tuple[str, ...]
    candidate: Finding
    shared: dict[str, Finding]
    events: tuple[Event, ...]
    iterations: int
    recoveries: int
    rejection_recoveries: int
    decision: dict | None
    feedback: ValidationFeedback | None
    tool_result: dict | None
    outcome: tuple[list[str], str, str, Interval | None, str | None]
    completed: bool
    relation: RelationalFinding | None
    attempted_relations: tuple[str, ...]
    route: str
    report: str


def require_graph():
    try:
        from langgraph.graph import END, START, StateGraph
        from langsmith import tracing_context
    except ImportError as exc:
        raise VideoError("Install the optional graph extra to run StateGraph") from exc
    return END, START, StateGraph, tracing_context


def run_graph(run: AgentRun, initial: tuple[Finding, ...]) -> tuple[tuple[Event, ...], str]:
    END, START, StateGraph, tracing_context = require_graph()

    def investigate(state: GraphState):
        candidates = run.investigate(state["initial"])
        return {"pending": (*sorted(candidates, key=lambda f: f.citation.interval.start_us), *run.relational_tasks)}

    def start_candidate(state: GraphState):
        if not state["pending"]:
            return {"route": "report"}
        candidate, *pending = state["pending"]
        task = candidate if isinstance(candidate, RelationalTask) else None
        return {
            "candidate": run.initial[task.observation_ids[0]] if task else candidate, "task": task, "pending": tuple(pending),
            "iterations": 0, "recoveries": 0, "rejection_recoveries": 0, "feedback": None, "tool_result": None,
            "relation": None, "attempted_relations": (), "task_findings": (),
            "route": "decide",
        }

    def unresolved(state: GraphState, reason: str):
        return {"outcome": ([state["candidate"].observation.id], "insufficient", reason, None, None), "route": "finish", "completed": False}

    def visible(state: GraphState):
        if task := state["task"]:
            ids = state["task_findings"]
            return ({identifier: run.initial[identifier] for identifier in task.observation_ids}
                    | {identifier: state["shared"][identifier] for identifier in ids})
        return run.visible_for(state["candidate"], shared=state["shared"])

    def decide(state: GraphState):
        limit = run.budget.max_verification_iterations
        if limit is not None and state["iterations"] >= limit:
            run.log("verification", "budget_exhausted", "Verification iteration limit reached.")
            return unresolved(state, "Verification iteration limit reached.")
        action = run.verification_action(
            state["candidate"], visible(state), state["iterations"], state["tool_result"],
            feedback=state["feedback"], task=state["task"],
        )
        if action is None:
            return unresolved(state, run.trace[-1].reason)
        return {
            "decision": action, "iterations": state["iterations"] + 1,
            "route": "inspect" if action["action"] == "inspect" else "validate",
        }

    def recover(state, action, code, reason, *, counter="recoveries", **details):
        seed = state["candidate"].observation.id
        limit = run.budget.max_rejection_recoveries if counter == "rejection_recoveries" else run.budget.max_recoveries
        remaining = limit - state.get(counter, 0)
        feedback: ValidationFeedback = {
            "code": code, "reason": reason, "candidate_id": seed,
            "remaining_recoveries": max(0, remaining - 1), **details,
        }
        run.log("verification", action, reason, (seed,), details=feedback)
        if remaining <= 0:
            return {"feedback": feedback, **unresolved(state, reason)}
        run.log("verification", "recovery", "Return validation feedback for a new evidence decision.",
                (seed,), details=feedback)
        return {"feedback": feedback, counter: state.get(counter, 0) + 1, "route": "decide"}

    def validate(state: GraphState):
        candidate = state["candidate"]
        seed = candidate.observation.id
        decision = state["decision"]
        if task := state["task"]:
            if decision["verdict"] == "insufficient":
                return unresolved(state, "Verification found insufficient relational evidence.")
            relation = run.validate_relation_proposal(candidate, decision["relation_proposal_id"], task=task)
            if relation is None:
                return recover(state, "relation_insufficient", "relation_proposal_invalid",
                               "Relational proposal failed evidence validation.")
            return {"route": "finish", "relation": relation}
        updates = {}
        relation = state["relation"]
        if (run.autonomous_relations and "relation_proposal_id" in decision
                and (relation is None or relation.status != "supported")):
            identifier = decision["relation_proposal_id"]
            attempted = state["attempted_relations"]
            if identifier not in attempted:
                if isinstance(identifier, str):
                    updates["attempted_relations"] = (*attempted, identifier)
                validated = run.validate_relation_proposal(candidate, identifier)
                if validated is not None:
                    updates["relation"] = validated

        try:
            outcome = run.verdict(candidate, decision, visible(state))
        except CorroborationRequired as exc:
            return updates | recover(state, "evidence_insufficient", "missing_corroboration", str(exc))
        except VideoError as exc:
            run.log("verification", "verdict_rejected", str(exc), (seed,), details={"stage": "verdict_validation"})
            return updates | unresolved(state, "Invalid verdict or citation.")
        ids, status, *_ = outcome
        if state["feedback"] and status == "unsupported" and ids == [seed]:
            return updates | unresolved(state, "Recovery yielded no additional cited evidence.")
        return updates | {"outcome": outcome, "route": "finish", "completed": True}

    def inspect(state: GraphState):
        scoped = visible(state)
        task = state["task"]
        try:
            result = run.reinspect(state["candidate"], state["decision"], scoped, publish=False, task=task)
        except InspectionRejected as exc:
            decision = state["decision"]
            guidance = {}
            if exc.code == "no_new_frames":
                fine = run.sampled_indices is not None and (task.id if task else state["candidate"].observation.id) not in run.fine_tasks
                guidance["guidance"] = (
                    "Every 500 ms sample in this interval is already in the evidence. "
                    + ("For new source frames request sampling_step_ms=250 with a visual_question over at most five "
                       "seconds, or shift the interval start so the 500 ms grid falls between existing samples."
                       if fine else "Shift the interval start so the 500 ms grid falls between existing samples."))
            return recover(
                state, "inspection_rejected", exc.code, str(exc), counter="rejection_recoveries", **guidance,
                requested={key: decision[key] if type(decision[key]) in (int, str) else None
                           for key in ("modality", "start_us", "end_us", "sampling_step_ms") if key in decision},
                constraints={
                    "modalities": ["frames"] if task else ["frames", "clip"],
                    "source_duration_us": run.video.duration_us,
                    **({"within_task": asdict(task.interval)} if task
                       else {"must_overlap": asdict(state["candidate"].citation.interval)}),
                    "max_span_us": MAX_INSPECTION_SPAN_US,
                    "remaining_inspections": run.budget.max_inspections - run.inspections,
                },
            )
        except VideoError as exc:
            run.log("verification", "tool_failure", str(exc), (state["candidate"].observation.id,))
            return unresolved(state, "Source inspection failed.")
        if result["status"] == "failed":
            return {"tool_result": result, **unresolved(state, "Source inspection failed.")}
        return {
            "shared": state["shared"] | {i: scoped[i] for i in result["ids"]},
            "tool_result": result, "route": "decide",
            **({"task_findings": (*state["task_findings"], *result["ids"])} if task else {}),
        }

    def finish(state: GraphState):
        if task := state["task"]:
            relation = state["relation"]
            event = run.finish_relational_task(task, relation, relation.reason if relation else state["outcome"][2])
            return {"events": (*state["events"], event)} if event else {}
        event = run.finish_verification(
            state["candidate"], visible(state), *state["outcome"], completed=state["completed"],
            relation_action=state["decision"] if state["completed"] and not run.autonomous_relations else None,
            validated_relation=state["relation"],
        )
        return {"events": (*state["events"], event)}

    def report(state: GraphState):
        events = run.finalize_events(state["events"])
        return {"events": events, "report": run.report(events)}

    def route(state: GraphState) -> str:
        return state["route"]

    previous_node = "START"

    def transition(destination):
        nonlocal previous_node
        run.log("workflow", "graph_transition", "StateGraph advanced.",
                details={"from": previous_node, "to": destination})
        previous_node = destination

    def traced(name, node):
        def execute(state: GraphState):
            transition(name)
            return node(state)

        return execute

    graph = StateGraph(GraphState)
    for name, node in (
        ("investigate", investigate), ("start_candidate", start_candidate), ("decide", decide),
        ("validate", validate), ("inspect", inspect), ("finish", finish), ("report", report),
    ):
        graph.add_node(name, traced(name, node))
    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", "start_candidate")
    graph.add_conditional_edges("start_candidate", route, ["decide", "report"])
    graph.add_conditional_edges("decide", route, ["inspect", "validate", "finish"])
    graph.add_conditional_edges("validate", route, ["decide", "finish"])
    graph.add_conditional_edges("inspect", route, ["decide", "finish"])
    graph.add_edge("finish", "start_candidate")
    graph.add_edge("report", END)

    # Only AgentRun spends call or tool units. The superstep cap is a separate safety net.
    step_limit = 4 * run.budget.max_agent_calls + 3 * run.budget.max_candidates + 12
    with tracing_context(enabled=False):
        result = graph.compile().invoke({"initial": initial, "events": (), "shared": {}}, {"recursion_limit": step_limit})
    transition("END")
    return result["events"], result["report"]
