"""Offline differential replay of the archived selection decisions."""
import json
from pathlib import Path

from google import genai
import httpx

import verification


BASELINE = Path(__file__).with_name("verification-autonomous-live") / "result.json"


def test_archived_request_diff_preserves_decisions(tmp_path, monkeypatch):
    baseline = json.loads(BASELINE.read_text())
    real_client = genai.Client
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    captures = []

    for enhanced in (False, True):
        saved_decisions = iter(baseline["decisions"])
        saved_media = iter(baseline["targeted_evidence"])
        calls = []

        def respond(request):
            body = json.loads(request.content)
            parts = body["contents"][0]["parts"]
            if any("inlineData" in part for part in parts):
                entry = next(saved_media)
                observations = []
                for finding in entry["findings"]:
                    obs = finding["observation"]
                    bounds = obs["evidence"]["interval"]
                    observations.append({
                        **{k: obs[k] for k in ("category", "description", "visibility_limits", "uncertainty")},
                        "frame_labels": [], "clip_interval_us": [bounds["start_us"], bounds["end_us"]],
                    })
                answer = {"observations": observations}
            else:
                context = json.loads(parts[0]["text"])
                decision = next(saved_decisions)
                assert context.get("candidate_id") == decision["candidate_id"]
                if decision["role"] == "verification":
                    calls.append({"context": context, "config": body["generationConfig"],
                                  "instruction": body["systemInstruction"], "decision": decision["decision"]})
                answer = decision["decision"]
            return httpx.Response(200, json={"candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]}}]})

        def client(**kwargs):
            kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
            return real_client(**kwargs)

        monkeypatch.setattr(genai, "Client", client)
        out = tmp_path / ("revised" if enhanced else "baseline")
        args = ["--output", str(out), "--autonomous-relations", "--authorize-footage-transfer",
                "--authorize-observation-text-transfer", "--question", baseline["answers"][0]["question"]]
        if enhanced:
            args.append("--relational-selection")
        assert verification.main(args) == 0
        result = json.loads((out / "result.json").read_text())
        assert result["events"] == baseline["events"]
        assert result["completion"] == baseline["completion"]
        assert result["physical_requests"] == baseline["physical_requests"] == 11
        assert len(calls) == 8
        captures.append(calls)
        (out / "reconstructed-verification-requests.json").write_text(json.dumps(calls, indent=2))

    old, new = captures
    for first, second in zip(old, new, strict=True):
        context = second["context"].copy()
        assert context.pop("relational_selection") is True
        context.pop("overlapping_observations")
        assert context == first["context"]
        assert first["instruction"] != second["instruction"]
    old_late, new_late = (next(c["context"] for c in arm if c["context"]["candidate_id"].startswith(
        "observation-ac83682fb5")) for arm in captures)
    assert len(old_late["evidence"]) == 1
    peer, = new_late["overlapping_observations"].values()
    assert peer["disposition"] == "deferred"
    assert "reception seating" in peer["description"]
    branches = new[0]["config"]["responseJsonSchema"]["anyOf"]
    relational, = [branch for branch in branches if "visual_question" in branch["properties"]]
    assert {"visual_question", "reason", "start_us", "end_us"} <= set(relational["required"])
    assert relational["properties"]["modality"]["enum"] == ["frames"]


def test_relational_question_and_existing_limits():
    from types import SimpleNamespace
    import pytest
    from security_augmented.agents import AgentRun, InspectionRejected
    from security_augmented.contracts import Interval
    from security_augmented.workflow import Budget

    candidate = SimpleNamespace(observation=SimpleNamespace(id="seed"), citation=SimpleNamespace(
        interval=Interval(0, 2_000_000),
    ))
    calls = []
    run = AgentRun(SimpleNamespace(duration_us=10_000_000), None,
                   lambda *args, **kwargs: calls.append((args, kwargs)) or (),
                   Budget(max_inspections=1), [], autonomous_relations=True, relational_selection=True)
    action = dict(modality="frames", start_us=0, end_us=2_000_000,
                  relational=True, reason="Relative motion is unresolved.")
    with pytest.raises(InspectionRejected) as exc:
        run.reinspect(candidate, action, {})
    assert exc.value.code == "relational_question_required" and not calls
    action["visual_question"] = "Do the figures become farther apart in the image?"
    assert run.reinspect(candidate, action, {})["status"] == "missing"
    assert len(calls) == 1 and calls[0][1] == {"relational": True, "visual_question": action["visual_question"]}
    with pytest.raises(InspectionRejected) as exc:
        run.reinspect(candidate, action, {})
    assert exc.value.code == "inspection_repeated"
    with pytest.raises(InspectionRejected) as exc:
        run.reinspect(candidate, action | {"end_us": 1_500_000}, {})
    assert exc.value.code == "inspection_budget_exhausted" and len(calls) == 1


def test_exact_live_relation_survives_failed_movement(tmp_path, monkeypatch):
    saved = json.loads((BASELINE.parent.parent / "verification-relational-selection-live" / "result.json").read_text())
    decisions = iter(saved["decisions"])
    media, = saved["targeted_evidence"]
    real_client = genai.Client
    seen = []

    def respond(request):
        body = json.loads(request.content)
        parts = body["contents"][0]["parts"]
        if any("inlineData" in part for part in parts):
            assert sum("inlineData" in part for part in parts) == len(media["inspection"]["frames"])
            content = media["relational_raw_response"]
        else:
            row = next(decisions)
            context = json.loads(parts[0]["text"])
            assert context.get("candidate_id") == row["candidate_id"]
            if row["role"] == "verification":
                assert context == row["context"]
            seen.append(row["decision"])
            content = json.dumps(row["decision"])
        return httpx.Response(200, json={"candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": content}]}}]})

    def client(**kwargs):
        kwargs["http_options"].client_args["transport"] = httpx.MockTransport(respond)
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture")
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    out = tmp_path / "replayed"
    assert verification.main(["--output", str(out), "--autonomous-relations", "--relational-selection",
                              "--authorize-footage-transfer", "--authorize-observation-text-transfer",
                              "--question", "What happened after the two people approached each other?"]) == 0
    current = json.loads((out / "result.json").read_text())
    assert seen == [row["decision"] for row in saved["decisions"]]
    assert current["physical_requests"] == saved["physical_requests"]
    assert current["completion"] == saved["completion"]
    actual, = current["targeted_evidence"]
    assert actual["inspection"] == media["inspection"]
    assert actual["relation"] == media["relation"]
    event, = [e for e in current["events"] if e["relation"]]
    assert event["verdict"] == "insufficient"
    assert event["observation_ids"][0].startswith("observation-da6fdebc40")
    prior = next(e for e in saved["events"] if e["observation_ids"] == event["observation_ids"])
    assert prior == (event | {"relation": None})
    relation = event["relation"]
    assert (relation["claim"], relation["status"], relation["continuity"]) == ("approach", "supported", "unresolved")
    assert relation["interval"] == media["relation"]["interval"]
    assert [f["id"] for c in relation["citations"] for f in c["frames"]] == [
        v["frame_id"] for v in media["relation"]["views"]
    ]
    verdict, = [row for row in current["trace"] if row["action"] == "relation_verdict"]
    assert verdict["details"] == relation
    assert current["answers"][0]["anchor"] == relation
    report = (out / "report.md").read_text()
    assert "Apparent convergence" in report and "Person continuity unresolved" in report


def test_autonomous_validator_rejects_invalid_canonical_reference():
    from dataclasses import replace
    from types import SimpleNamespace

    from security_augmented.agents import AgentRun
    from security_augmented.contracts import FrameEvidence, Interval
    from security_augmented.relations import review_from_dict
    from security_augmented.workflow import Budget

    saved = json.loads((BASELINE.parent.parent / "verification-relational-selection-live" / "result.json").read_text())
    entry, = saved["targeted_evidence"]
    review = review_from_dict(entry["relation"])
    broken = replace(review, views=(replace(review.views[0], frame_id="unknown-canonical-id"), *review.views[1:]))
    seed = SimpleNamespace(observation=SimpleNamespace(id="seed"),
                           citation=SimpleNamespace(interval=Interval(**entry["interval"])))
    inspection = SimpleNamespace(id=entry["inspection"]["id"],
                                 frames=tuple(FrameEvidence(**f) for f in entry["inspection"]["frames"]))
    run = AgentRun(SimpleNamespace(width=384, height=288), None, None, Budget(), [], autonomous_relations=True)
    run.relation_proposals["seed"] = {inspection.id: SimpleNamespace(inspection=inspection, relation=broken)}
    assert run.validate_relation_proposal(seed, inspection.id) is None
    rejection, = run.trace
    assert rejection.action == "relation_rejected"
    assert "outside visible source evidence" in rejection.reason
