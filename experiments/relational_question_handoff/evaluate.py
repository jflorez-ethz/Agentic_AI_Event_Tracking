"""Offline only: real archived observations, real local frame decoding, scripted SDK transport."""
from dataclasses import replace
import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import TypeAdapter

from handoff import QuestionDecider, QuestionRun
from security_augmented.agents import AgentModels, AgentRun, GeminiDecider
from security_augmented.gemini import GeminiAdapter
from security_augmented.graph_workflow import run_graph
from security_augmented.workflow import Analysis, InspectionPlan, _observe_video, _supported_timeline

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "experiments/mvp_live.6R7h4T/run/analysis.json"
QUESTIONS = {
    "spacing": "What changes, if any, are visible in the spacing between the two silhouettes across these frames?",
    "visibility": "Which portions of this interval, if any, show two separately distinguishable silhouettes?",
}


def evaluate(case, handoff=True, forged=False, *, capture_assignment=None):
    record = json.loads(ARCHIVE.read_text())
    archive = TypeAdapter(Analysis).validate_python(record["analysis"])
    video = replace(archive.video, source_path=str(ROOT / "data/raw/Meet_WalkSplit_pts.mp4"))
    initial = archive.observations
    ids = [f.observation.id for f in initial]
    q = QUESTIONS.get(case)
    selected = [ids[i] for i in (1, 3, 5, 7)]
    displaced = None
    if q:
        displaced = ids[1 if case == "spacing" else 7]
        selected.remove(displaced)
    elif case in ("disjoint", "appearance"):
        indices = (1, 7, 10) if case == "disjoint" else (0, 1, 10)
        initial = tuple(initial[i] for i in indices)
        selected = [f.observation.id for f in initial]
    elif case != "baseline":
        raise ValueError(case)
    contexts, frames, media_counts, schemas = [], [], [], []
    transitions = {t.details["observation_id"]: {k: v for k, v in t.details.items() if k != "interval"}
                   for t in archive.trace if t.action == "transition_evidence"}

    def respond(request):
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        if any("inlineData" in part for part in parts):
            media_counts.append(sum("inlineData" in part for part in parts))
            value = {"observations": [], "relation": None}
        else:
            c = json.loads(parts[0]["text"])
            if "max_candidates" in c:
                schemas.append(body["generationConfig"]["responseJsonSchema"])
                value = {"action": "delegate", "ids": selected, "reason": "Controlled allocation.",
                         "dispositions": [{"id": i, "status": "deferred", "reason": "Unverified lead."}
                                          for i in c["evidence"] if i not in selected]}
                if q:
                    value["relational_tasks"] = [{"observation_ids": [ids[3], ids[5]],
                                                   **({"visual_question": q} if handoff else {})}]
            elif task := c.get("relational_task"):
                contexts.append(task)
                if capture_assignment is not None:
                    capture_assignment(body)
                    value = {"action": "relation_verdict", "verdict": "insufficient",
                             "reason": "Offline serialization fixture."}
                elif forged:
                    value = {"action": "relation_verdict", "verdict": "supported", "relation_proposal_id": q,
                             "reason": "Attempt to select text without a proposal."}
                elif c["last_tool_result"] is None:
                    value = {"action": "inspect", "modality": "frames", "relational": True,
                             "start_us": 6030000, "end_us": 7030000,
                             "sampling_step_ms": 250 if case == "spacing" else 500,
                             "reason": "The source descriptions leave visibility uncertain.",
                             "visual_question": task.get("visual_question", task["objective"])}
                else:
                    value = {"action": "relation_verdict", "verdict": "insufficient",
                             "reason": "The inspection leaves correspondence unresolved."}
            elif "candidate_id" in c:
                i = c["candidate_id"]
                value = {"action": "verdict", "ids": [i], "correspondence": [], "verdict": "insufficient",
                         "reason": "Controlled individual check."}
                if i in transitions:
                    value.update(verdict="supported", transition=transitions[i])
            else:
                value = {"action": "report", "lead_id": None, "emphasis": "uncertainty", "reason": "Report findings."}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(value)}]}}]})

    with patch.dict(os.environ, {"GEMINI_API_KEY": "offline", "GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        adapter = GeminiAdapter.from_env(authorized=True, single_request=True,
                                         client_args={"transport": httpx.MockTransport(respond)})
        def inspect(interval, modality, **options):
            entry = _observe_video(video, adapter, interval, modality, "targeted", InspectionPlan(),
                                   model_guided=True, **options)
            frames.append([f.id for f in entry.inspection.frames])
            return (entry,)

        with adapter.client:
            decider = (QuestionDecider if handoff else GeminiDecider)(adapter, AgentModels(**record["models"]))
            run = (QuestionRun if handoff else AgentRun)(
                video, decider, inspect, archive.budget, [], autonomous_relations=True, relational_selection=True,
                relational_tasks=True, sampled_indices={f.display_index for e in archive.evidence for f in e.inspection.frames})
            events, report = run_graph(run, initial)
    timeline = _supported_timeline(events)
    replay = replace(archive, timeline=timeline, unresolved=tuple(e for e in events if e.verdict != "supported"))
    return {"case": case, "displaced": displaced, "selected": selected, "tasks_received": contexts,
            "outcomes": run.relational_outcomes, "frames": frames, "submitted_images": media_counts,
            "completion": run.completion(), "report": report, "schemas": schemas,
            "supported_ids": [e.observation_ids for e in timeline],
            "anchor_found": replay.ask("What happened after the two people approached each other?").anchor is not None}


if __name__ == "__main__":
    for case in ("baseline", *QUESTIONS, "disjoint", "appearance"):
        for mode in (False, True):
            r = evaluate(case, mode)
            print(json.dumps({"interface": "question" if mode else "generic",
                              "assignment": next(iter(r["tasks_received"]), None),
                              "verification_task_decisions": len(r["tasks_received"]), **{
                k: r[k] for k in ("case", "selected", "displaced", "outcomes", "frames", "submitted_images", "anchor_found")}}))
