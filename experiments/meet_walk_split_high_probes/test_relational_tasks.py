"""Run the saved movement decision with and without an independent task."""
import json
from pathlib import Path

import pytest

from probe import CONTINUATION_RECORD, SOURCE, restore
from security_augmented.agents import AgentRun
from security_augmented.graph_workflow import run_graph
from security_augmented.video import ingest
from security_augmented.workflow import Budget

HERE = Path(__file__).parent
SAVED = json.loads((HERE / "isolated-selection-live/result.json").read_text())["decision"]
SEED = SAVED["ids"][0]
PEER = "observation-83b23ba3dbd65521e8b8791098baf6da421ec6827c14ce5b560be5a474602aed"


def test_saved_movement_does_not_close_relational_task():
    archive = json.loads(CONTINUATION_RECORD.read_text())["analysis"]
    initial = tuple(f for f in restore(archive) if f.observation.id in (SEED, PEER))
    calls = []

    def replay(role, context):
        if role == "investigation":
            return {"action": "delegate", "ids": [SEED], "reason": "Check movement.",
                    "dispositions": [{"id": PEER, "status": "deferred", "reason": "Do not verify independently."}],
                    **({"relational_tasks": [{"observation_ids": [SEED, PEER]}]} if enabled else {})}
        if role == "reporting":
            return {"action": "report", "lead_id": SEED, "emphasis": "evidence", "reason": "Report."}
        calls.append(context)
        if "relational_task" in context:
            assert any(t.action == "verdict" and t.details["completed"] for t in run.trace)
            assert run.completion()["relational_tasks"][0]["status"] == "pending"
            return {"action": "relation_verdict", "verdict": "insufficient", "reason": "Needs more visual evidence."}
        return SAVED

    states = []
    for enabled in (False, True):
        run = AgentRun(ingest(SOURCE), replay, lambda *_: (), Budget(max_candidates=2), [],
                       autonomous_relations=enabled, relational_tasks=enabled)
        events, report = run_graph(run, initial)
        states.append((events, run.completion(), report))
    baseline, extended = states
    assert baseline[0] == extended[0]
    assert baseline[1]["completed_checks"] == extended[1]["completed_checks"] == 1
    assert extended[1]["relational_tasks"][0]["status"] == "unresolved"
    assert extended[1]["observation_dispositions"] == baseline[1]["observation_dispositions"]
    assert "Relational task unresolved" in extended[2]
    assert len(calls) == 3


def archived_pair():
    archive = json.loads(CONTINUATION_RECORD.read_text())["analysis"]
    return ingest(SOURCE), tuple(f for f in restore(archive) if f.observation.id in (SEED, PEER))


def test_delegation_rejects_bad_sources_scopes_duplicates_and_caps():
    from dataclasses import replace

    from security_augmented.contracts import Interval, VideoError

    video, pair = archived_pair()
    visible = {f.observation.id: f for f in pair}
    dispositions = {SEED: {"status": "delegated"}, PEER: {"status": "deferred"}}
    rows = [{"observation_ids": [SEED, PEER]}]
    run = AgentRun(video, None, None, Budget(max_candidates=3), [], autonomous_relations=True, relational_tasks=True)
    tasks = run._relation_delegations(rows, visible, dispositions, 1)
    assert len(tasks) == 1
    assert run._relation_delegations([{"observation_ids": [PEER, SEED]}], visible, dispositions, 1) == tasks
    with pytest.raises(VideoError, match="unique"):
        run._relation_delegations([*rows, {"observation_ids": [PEER, SEED]}], visible, dispositions, 1)
    with pytest.raises(VideoError, match="candidate budget"):
        run._relation_delegations(rows, visible, dispositions, 3)
    with pytest.raises(VideoError, match="only observation IDs"):
        run._relation_delegations([rows[0] | {"claim": "approach"}], visible, dispositions, 1)
    with pytest.raises(VideoError, match="incompatible source"):
        bad = replace(visible[PEER], citation=replace(visible[PEER].citation, video_id="foreign"))
        run._relation_delegations(rows, visible | {PEER: bad}, dispositions, 1)
    with pytest.raises(VideoError, match="interval does not match"):
        bad = replace(visible[PEER], citation=replace(visible[PEER].citation, interval=Interval(0, 1)))
        run._relation_delegations(rows, visible | {PEER: bad}, dispositions, 1)
    with pytest.raises(VideoError, match="noncanonical"):
        f = visible[PEER]
        bad = replace(f, citation=replace(f.citation, frames=(replace(f.citation.frames[0], pts=-1), *f.citation.frames[1:])))
        run._relation_delegations(rows, visible | {PEER: bad}, dispositions, 1)


def test_spent_inspection_and_call_budgets_leave_task_unresolved():
    video, pair = archived_pair()
    for budget in (Budget(max_inspections=0), Budget(max_agent_calls=3)):
        inspections = []

        def decide(role, context):
            if role == "investigation":
                return {"action": "delegate", "ids": [SEED], "reason": "Investigate.",
                        "dispositions": [{"id": PEER, "status": "deferred", "reason": "Lead only."}],
                        "relational_tasks": [{"observation_ids": [SEED, PEER]}]}
            if role == "reporting":
                return {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Report."}
            if "relational_task" in context:
                return {"action": "inspect", "reason": "Unclear positions.", "visual_question": "How do the paths relate?",
                        "start_us": 10_000_000, "end_us": 13_000_001, "modality": "frames", "relational": True}
            return SAVED

        run = AgentRun(video, decide, lambda *a, **k: inspections.append(a) or (), budget, [],
                       autonomous_relations=True, relational_tasks=True)
        run_graph(run, pair)
        assert not inspections
        assert run.completion()["relational_tasks"][0]["status"] == "unresolved"
        assert run.completion()["completed_checks"] == 1


@pytest.mark.parametrize("mode", ["supported", "insufficient", "uncertain", "empty", "uninspected"])
def test_sdk_payload_and_archived_media_reach_independent_event(tmp_path, monkeypatch, mode):
    import httpx
    from google import genai
    import verification

    saved = json.loads((HERE / "verification-relational-selection-live/result.json").read_text())
    media, = saved["targeted_evidence"]
    earlier = next(d["candidate_id"] for d in saved["decisions"] if d["decision"]["action"] == "inspect")
    other = saved["decisions"][0]["candidate_id"]
    if mode != "supported":
        prior = json.loads((HERE / "isolated-perception-live/result.json").read_text())
        media = prior["entry"]
        earlier, other = SEED, PEER
    received = []
    real_client = genai.Client

    def respond(request):
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        if any("inlineData" in p for p in parts):
            assert sum("inlineData" in p for p in parts) == len(media["inspection"]["frames"])
            text = media["relational_raw_response"]
            if mode == "empty":
                text = json.dumps({"observations": [], "relation": None})
            if mode == "uncertain":
                result = json.loads(text)
                result["relation"]["claim"] = "unresolved"
                result["relation"]["views"][-1]["marks"] = None
                text = json.dumps(result)
            received.append({"media": "recorded proposal replayed without changes"})
        else:
            context = json.loads(parts[0]["text"])
            schema = body["generationConfig"]["responseJsonSchema"]
            received.append({"context": context, "schema": schema, "instruction": body["systemInstruction"]})
            if context.get("independent_relational_tasks"):
                assert "relational_tasks" in schema["anyOf"][-1]["properties"]
                assert not any(k in context for k in ("relational_reviews", "relational_proposals"))
                answer = {"action": "delegate", "ids": [SEED], "reason": "Investigate visible movements.",
                          "relational_tasks": [{"observation_ids": [earlier, other]}],
                          "dispositions": [{"id": k, "status": "deferred", "reason": "Remains unverified."}
                                           for k in context["evidence"] if k != SEED]}
            elif task := context.get("relational_task"):
                assert task["observation_ids"] == sorted([earlier, other])
                assert task["objective"] == "Assess how the visible movements relate, if at all."
                assert set(context["dispositions"].values()) == (
                    {"deferred"} if mode == "supported" else {"deferred", "delegated"})
                assert "relational_reviews" not in context
                assert all("no_relation" not in branch["properties"].get("verdict", {}).get("enum", [])
                           for branch in schema["anyOf"])
                if mode == "uninspected" or mode == "empty" and context["last_tool_result"] is not None:
                    answer = {"action": "relation_verdict", "verdict": "no_relation", "reason": "No proposal."}
                elif context["last_tool_result"] is None:
                    assert context["relational_proposals"] == {}
                    assert all("marks" not in obs and "claim" not in obs for obs in context["evidence"].values())
                    answer = {"action": "inspect", "reason": "Positions need a visual check.",
                              "visual_question": "How do the two visible paths change relative to each other?",
                              "modality": "frames", "relational": True, **media["interval"]}
                else:
                    identifier, = context["relational_proposals"]
                    answer = {"action": "relation_verdict", "verdict": "supported",
                              "relation_proposal_id": identifier, "reason": "Use the checked visual proposal."}
            elif "candidate_id" in context:
                assert context["candidate_id"] == SEED
                answer = SAVED
            else:
                answer = {"action": "report", "lead_id": None, "emphasis": "evidence", "reason": "Report findings."}
            text = json.dumps(answer)
        return httpx.Response(200, json={"candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    out = tmp_path / "run"
    assert verification.main(["--autonomous-relations", "--relational-tasks", "--output", str(out),
                              "--authorize-observation-text-transfer", "--authorize-footage-transfer",
                              "--question", "What happened after the two people approached each other?"]) == 0
    result = json.loads((out / "result.json").read_text())
    assert result["physical_requests"] == {"empty": 5, "uninspected": 3}.get(mode, 6)
    assert result["max_physical_role_requests"] + result["max_physical_media_requests"] == 32
    task, = result["completion"]["relational_tasks"]
    events = [event for event in result["events"] if event["category"] == "relational_task"]
    if mode == "supported":
        assert task["status"] == "supported"
        event, = events
        assert event["relation"]["status"] == "supported" and event["relation"]["continuity"] == "unresolved"
        assert result["answers"][0]["anchor"] == event["relation"]
        from retrieval import load_analysis
        assert load_analysis(out / "result.json").ask("What happened after the two people approached each other?").anchor
        assert "Movement verification: completed (1/1 checks completed)" in (out / "report.md").read_text()
        assert "Apparent convergence" in (out / "report.md").read_text()
    else:
        assert task["status"] == "unresolved" and not events
        assert result["answers"][0]["anchor"] is None
        assert "Relational task unresolved" in (out / "report.md").read_text()
    if mode != "uninspected":
        assert result["targeted_evidence"][0]["inspection"] == media["inspection"]
    else:
        assert not result["targeted_evidence"]
    assert result["completion"]["completed_checks"] == 1
    (out / "mock-requests.json").write_text(json.dumps(received, indent=2))
