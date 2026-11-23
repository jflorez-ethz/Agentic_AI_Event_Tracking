"""Scripted review replay over the archived WalkSplit 500 ms handoff."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

from probe import CONTINUATION_RECORD, SOURCE, archived_search, restore, save
from verification import HANDOFF, load_reviews
from security_augmented.agents import AgentRun
from security_augmented.graph_workflow import run_graph
from security_augmented.relations import Mark, Review, View
from security_augmented.video import ingest
from security_augmented.contracts import Interval
from security_augmented.workflow import Analysis, Budget, InspectionPlan


def main(output):
    archived = json.loads(CONTINUATION_RECORD.read_text())["analysis"]
    handoff = json.loads((HANDOFF / "decision.json").read_text())
    initial = restore(archived)
    video = ingest(SOURCE)
    frames = {frame.display_index: frame for f in initial for frame in f.citation.frames}

    def review(claim, indices, marks, **kwargs):
        first, *_, last = [frames[index] for index in indices]
        return Review(claim, Interval(first.source_time_us, last.source_time_us + 1),
                      tuple(View(frames[index].id, None if row is None else tuple(Mark(*m) for m in row))
                            for index, row in zip(indices, marks, strict=True)), **kwargs)

    reviews = {
        "approach": review("approach", (150, 163), (((122, 141, 4), (169, 150, 4)),
                                                    ((130, 138, 4), (157, 146, 4)))),
        "divergence": review("visible_divergence", (250, 325), (((93, 112, 4), (82, 135, 4)),
                                                               ((64, 94, 4), (55, 137, 4))), distinct_paths=True),
        "overlap": review("unresolved", (163, 175, 188), (None, None, None)),
    }
    choices = {candidate: choice for candidate, choice in zip(
        handoff["ids"][:3], ("overlap", "approach", "divergence"), strict=True,
    )}
    output.mkdir(parents=True, exist_ok=False)
    save(output, "reviews.json", {
        "source_sha256": video.sha256,
        "review_scope": "Provisional single-reviewer marks for offline contract replay.",
        "reviews": {key: asdict(value) for key, value in reviews.items()},
    })
    reviews = load_reviews(output / "reviews.json", video, initial, InspectionPlan(**archived["coverage"]["plan"]))
    decisions = []

    def decide(role, context):
        if role == "investigation":
            if context["last_tool_result"] is None:
                return {"action": "search", **archived_search(archived)["interval"], "reason": "Replay archived search."}
            return handoff
        if role == "reporting":
            return {"action": "report", "reason": "Report reviewed evidence and uncertainty.",
                    "lead_id": None, "emphasis": "uncertainty"}
        seed = context["candidate_id"]
        decision = {"action": "verdict", "verdict": "insufficient", "ids": [seed], "correspondence": [],
                    "reason": "No independent movement verdict was attempted in this scripted replay."}
        if choice := choices.get(seed):
            assert choice in context["relational_reviews"]
            decision["relation_review_id"] = choice
        decisions.append({"candidate_id": seed, "decision": decision})
        return decision

    budget = Budget(**archived["budget"])
    trace = []
    run = AgentRun(video, decide, lambda *_: (), budget, trace, relation_reviews=reviews)
    events, report = run_graph(run, initial)
    analysis = Analysis(video, (), initial, (), events, tuple(trace), report, budget)
    questions = ("What happened after the two people approached each other?",
                 "What happened after local divergence?",
                 "What happened after the same two people separated?")
    save(output, "replay.json", {
        "decisions": decisions,
        "events": [asdict(event) for event in events],
        "trace": [asdict(row) for row in trace],
        "answers": [{"question": q, **asdict(analysis.ask(q))} for q in questions],
    })
    (output / "report.md").write_text(report)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
