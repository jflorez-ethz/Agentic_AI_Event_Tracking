"""Prepare, run with authorization, or compare the isolated Investigation A/B pair."""
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from google import genai
import httpx

from probe import restore, save
from security_augmented.agents import AgentModels, AgentRun, GeminiDecider
from security_augmented.contracts import Video, VideoError
from security_augmented.gemini import GeminiAdapter
from security_augmented.workflow import Budget

RUN = Path(__file__).with_name("independent-relational-tasks-retry-live") / "result.json"
FIELD = "unseen_observation_coverage"


class CoverageDecider(GeminiDecider):
    """Preserve the generation budget in the frozen A/B request manifests."""

    investigation_max_output_tokens = 16384


def coverage(initial, visible):
    """Merge intersecting or touching half-open citations, counting each unseen record once."""
    intervals = sorted(
        (f.citation.interval.start_us, f.citation.interval.end_us)
        for f in initial if f.observation.id not in visible
    )
    groups = []
    for start, end in intervals:
        if groups and start <= groups[-1]["end_us"]:
            groups[-1]["end_us"] = max(groups[-1]["end_us"], end)
            groups[-1]["observation_count"] += 1
        else:
            groups.append(dict(start_us=start, end_us=end, observation_count=1))
    return groups


def capture_request(context, decision, models):
    captured = []

    def respond(request):
        assert request.url.path == f"/v1beta/models/{models.investigation}:generateContent"
        assert not captured
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(decision)}]},
        }]})

    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}), genai.Client(
        api_key="offline-fixture", vertexai=False, http_options={
            "api_version": "v1beta", "client_args": {"transport": httpx.MockTransport(respond)},
        },
    ) as client:
        adapter = GeminiAdapter(client=client, model=models.video, single_request=True)
        assert CoverageDecider(adapter, models)("investigation", context) == decision
    request, = captured
    return request


def load_archive():
    prior = json.loads(RUN.read_text())
    scan = json.loads(Path(prior["archived_scan"]).read_text())["analysis"]
    video = Video(**(scan["video"] | {"frame_pts": tuple(scan["video"]["frame_pts"])}))
    initial = restore(scan)
    budget = Budget(**prior["budget"])
    models = AgentModels(**prior["models"])
    archived, = (d for d in prior["decisions"] if d["role"] == "investigation")
    return video, initial, budget, models, archived


def investigation_run(video, budget, decide):
    return AgentRun(video, decide, None, budget, [], autonomous_relations=True,
                    relational_selection=True, relational_tasks=True)


def prepare():
    video, initial, budget, models, archived = load_archive()
    baseline, decision = archived["context"], archived["decision"]
    extra = coverage(initial, baseline["evidence"])
    treatment = baseline | {FIELD: extra}

    requests = {arm: capture_request(context, decision, models)
                for arm, context in (("A", baseline), ("B", treatment))}
    def unpack(request):
        body = json.loads(json.dumps(request))
        part = body["contents"][0]["parts"][0]
        return body, json.loads(part.pop("text"))

    body_a, context_a = unpack(requests["A"])
    body_b, context_b = unpack(requests["B"])
    assert body_a == body_b and context_a == baseline
    assert context_b.pop(FIELD) == extra and context_a == context_b
    replay = {}

    def archived_choice(role, context):
        assert role == "investigation" and context == baseline
        return decision

    agent = investigation_run(video, budget, archived_choice)
    picked = agent.investigate(initial)
    assert [f.observation.id for f in picked] == decision["ids"]
    assert not agent.relational_tasks and not agent.retrievals
    replay["delegated_ids"] = decision["ids"]
    replay["omitted_ids"] = sorted(agent.initial.keys() - agent.dispositions.keys())

    for group in extra:
        contexts = []

        def search_choice(role, context):
            assert role == "investigation"
            contexts.append(context)
            if len(contexts) == 1:
                assert context == baseline
                return {"action": "search", "reason": "Offline coverage check.",
                        "start_us": group["start_us"], "end_us": group["end_us"]}
            raise VideoError("End of offline search check")

        investigation_run(video, budget, search_choice).investigate(initial)
        result = contexts[-1]["last_tool_result"]
        assert len(result["ids"]) == group["observation_count"]
        replay.setdefault("scripted_search_checks", []).append(group | {"result": result})
    return requests, {
        "request_diff": {"added_context_field": FIELD, "value": extra},
        "replay": replay, "budget": asdict(budget), "models": asdict(models),
        "request_source": "SDK mock transport",
    }


def live_arm(pair_dir, arm):
    video, initial, budget, models, archived = load_archive()
    baseline = archived["context"]
    expected = baseline if arm == "A" else baseline | {FIELD: coverage(initial, baseline["evidence"])}
    fixture = Path(__file__).with_name("investigation-coverage-ab-offline") / f"request-{arm}.json"
    expected_request = json.loads(fixture.read_text())
    requests, decisions = [], []
    result = {"arm": arm, "models": asdict(models), "budget": asdict(budget),
              "decisions": decisions, "physical_requests": requests}

    def before_send(request):
        if (len(requests) >= 2 or len(requests) >= len(decisions)
                or request.url.path != f"/v1beta/models/{models.investigation}:generateContent"):
            raise VideoError("Unexpected request or physical Investigation attempt limit reached")
        body = json.loads(request.content)
        if not requests and body != expected_request:
            raise VideoError("First SDK request does not match the offline manifest")
        if requests and body.get("systemInstruction") != expected_request.get("systemInstruction"):
            raise VideoError("Continuation changed the system instructions")
        requests.append({"number": len(requests) + 1, "body": body})
        save(output, "result.json", result)

    def after_response(response):
        record = requests[-1]
        record["http_status"] = response.status_code
        if response.is_success:
            # Record the exact response text, including invalid or incomplete candidates.
            response.read()
            record["raw_response"] = response.text
        save(output, "result.json", result)

    def decide(role, context):
        if role != "investigation" or len(decisions) >= 2:
            raise VideoError("Only two Investigation decisions are allowed")
        if not decisions and context != baseline:
            raise VideoError("Rebuilt initial context does not match the archive")
        if arm == "B":
            context = context | {FIELD: coverage(initial, context["evidence"])}
        if not decisions and context != expected:
            raise VideoError("Initial context has an unexpected A/B difference")
        record = {"context": context, "decision": None}
        decisions.append(record)
        try:
            record["decision"] = decider(role, context)
            return record["decision"]
        finally:
            record["diagnostics"] = decider.calls[-1]
            save(output, "result.json", result)

    pair_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output = pair_dir / arm
    output.mkdir(mode=0o700)
    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        adapter = GeminiAdapter.from_env(authorized=True, model=models.video, single_request=True,
                                         client_args={"follow_redirects": False, "event_hooks": {
                                             "request": [before_send], "response": [after_response],
                                         }})
        decider = CoverageDecider(adapter, models)
        run = investigation_run(video, budget, decide)
        with adapter.client:
            selected = run.investigate(initial)

    events = [asdict(event) for event in run.trace]
    movement_ids = [finding.observation.id for finding in selected]
    searches = [event["details"] for event in events if event["action"] == "search"]
    retrieved = [identifier for event in events if event["action"] == "tool_result"
                 for identifier in event["observation_ids"]]
    seen = set(baseline["evidence"]) | set(retrieved)
    result.update(
        status="delegated" if any(event["action"] == "delegate" for event in events) else "no_valid_delegation",
        trace=events, searches=searches, retrieved_ids=retrieved,
        movement_ids=movement_ids, relational_tasks=[asdict(task) for task in run.relational_tasks],
        slots_used=len(movement_ids) + len(run.relational_tasks),
        dispositions=list(run.dispositions.values()),
        unseen_ids=sorted(run.initial.keys() - seen),
        omitted_ids=sorted(run.initial.keys() - run.dispositions.keys()),
        remaining_agent_calls=run.remaining, elapsed_ms=sum(
            row["diagnostics"]["elapsed_ms"] for row in decisions),
    )
    save(output, "result.json", result)


def compare(pair_dir):
    arms = {arm: json.loads((pair_dir / arm / "result.json").read_text()) for arm in ("A", "B")}
    a, b = arms.values()
    if a["models"] != b["models"] or a["budget"] != b["budget"]:
        raise ValueError("Runs do not share the same models and budgets")
    context_a = a["decisions"][0]["context"]
    context_b = b["decisions"][0]["context"]
    if {key: value for key, value in context_b.items() if key != FIELD} != context_a:
        raise ValueError("Unmatched initial Investigation contexts")
    keys = ("status", "searches", "retrieved_ids", "movement_ids", "relational_tasks", "slots_used",
            "dispositions", "unseen_ids", "omitted_ids", "remaining_agent_calls", "elapsed_ms")
    comparison = {}
    for arm, row in arms.items():
        other = arms["B" if arm == "A" else "A"]
        calls = [entry["diagnostics"] for entry in row["decisions"]]
        comparison[arm] = {
            **{key: row[key] for key in keys},
            "physical_requests": len(row["physical_requests"]),
            "role_calls": calls,
            "movement_ids_only_in_other_arm": sorted(set(other["movement_ids"]) - set(row["movement_ids"])),
            "relational_task_ids_only_in_other_arm": sorted(
                {task["id"] for task in other["relational_tasks"]}
                - {task["id"] for task in row["relational_tasks"]}),
        }
    return comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--output", type=Path, help="Generate offline SDK fixtures")
    modes.add_argument("--live-arm", choices=("A", "B"))
    modes.add_argument("--compare", action="store_true")
    parser.add_argument("--pair-dir", type=Path)
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    args = parser.parse_args(argv)
    if args.output:
        requests, report = prepare()
        args.output.mkdir(mode=0o700)
        for arm, request in requests.items():
            save(args.output, f"request-{arm}.json", request)
        save(args.output, "replay.json", report)
    elif not args.pair_dir:
        parser.error("--pair-dir is required")
    elif args.compare:
        print(json.dumps(compare(args.pair_dir), indent=2))
    elif not args.authorize_observation_text_transfer:
        parser.error("Explicit authorization to send archived observation text is required")
    else:
        live_arm(args.pair_dir, args.live_arm)


if __name__ == "__main__":
    main()
