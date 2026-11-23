"""Offline preparation and explicitly authorized Investigation-only paired evaluation."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import random
from unittest.mock import patch

import httpx
from pydantic import TypeAdapter

from security_augmented.agents import AgentModels, AgentRun, GeminiDecider
from security_augmented.gemini import GeminiAdapter
from security_augmented.workflow import Analysis, VideoError

RUN = Path(__file__).resolve().parents[1] / "mvp_live.6R7h4T/run/analysis.json"
SENTENCE = ("Before committing the available slots, consider whether verifying the selected observations "
            "separately would leave a specific, visually answerable question about their relationship "
            "unresolved, and weigh that question against the individual check it would displace.")
CASES = {"full": None, "disjoint": (1, 7, 10), "appearance": (0, 1, 10)}


class Revised(GeminiDecider):
    def _request(self, call, **kwargs):
        kwargs["config"]["system_instruction"] += " " + SENTENCE
        return super()._request(call, **kwargs)


def execute(case, arm, *, transport=None, expected=None, output=None):
    saved = json.loads(RUN.read_text())
    analysis = TypeAdapter(Analysis).validate_python(saved["analysis"])
    initial = analysis.observations
    if CASES[case] is not None:
        initial = tuple(initial[i] for i in CASES[case])
    call_limit = 2 if len(initial) > max(8, analysis.budget.max_candidates) else 1
    result = {"requests": [], "responses": [], "decisions": []}

    def persist():
        if output:
            tmp = output.with_suffix(".tmp")
            tmp.write_text(json.dumps(result, indent=2))
            tmp.replace(output)

    def before(request):
        body = json.loads(request.content)
        if (len(result["requests"]) >= min(len(result["decisions"]), call_limit)
                or not request.url.path.endswith("/models/gemini-3.6-flash:generateContent")):
            raise VideoError("Unexpected physical request")
        if expected and not result["requests"] and body != expected:
            raise VideoError("First request differs from its offline capture")
        result["requests"].append(body)
        persist()

    def after(response):
        response.read()
        result["responses"].append({"http_status": response.status_code, "body": response.text})
        persist()

    options = {"follow_redirects": False, "event_hooks": {"request": [before], "response": [after]}}
    env = {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}
    if transport is not None:
        options["transport"] = transport
        env["GEMINI_API_KEY"] = "offline"
    with patch.dict(os.environ, env):
        adapter = GeminiAdapter.from_env(authorized=True, single_request=True, client_args=options)
        with adapter.client:
            model = (Revised if arm == "B" else GeminiDecider)(adapter, AgentModels(**saved["models"]))

            def decide(role, context):
                if role != "investigation" or len(result["decisions"]) >= call_limit:
                    raise VideoError("Investigation-only decision budget exhausted")
                row = {}
                result["decisions"].append(row)
                try:
                    row["decision"] = model(role, context)
                    return row["decision"]
                finally:
                    row["diagnostics"] = model.calls[-1]
                    persist()

            agent = AgentRun(analysis.video, decide, None, analysis.budget, [], autonomous_relations=True,
                             relational_selection=True, relational_tasks=True)
            picked = agent.investigate(initial)
    result.update(valid=any(t.action == "delegate" for t in agent.trace),
                  movements=[f.observation.id for f in picked], relations=[asdict(t) for t in agent.relational_tasks],
                  dispositions=agent.dispositions, omitted=sorted(agent.initial.keys() - agent.dispositions.keys()),
                  trace=[asdict(t) for t in agent.trace])
    persist()
    return result


def prepare(case):
    # A scripted abstention exercises serialization only.
    def reply(request):
        ids = json.loads(json.loads(request.content)["contents"][0]["parts"][0]["text"])["evidence"]
        decision = {"action": "delegate", "ids": [], "reason": "Offline fixture.",
                    "dispositions": [{"id": i, "status": "deferred", "reason": "Fixture."} for i in ids]}
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps(decision)}]}}]})
    captures = {arm: execute(case, arm, transport=httpx.MockTransport(reply))["requests"][0] for arm in "AB"}
    modified = deepcopy(captures["A"])
    modified["systemInstruction"]["parts"][0]["text"] += " " + SENTENCE
    if modified != captures["B"]:
        raise ValueError("SDK requests differ beyond the single sentence")
    return captures


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["prepare", "live"])
    p.add_argument("output", type=Path)
    p.add_argument("--case", choices=CASES, default="full")
    p.add_argument("--authorize-observation-text-transfer", action="store_true")
    args = p.parse_args()
    if args.mode == "live" and not args.authorize_observation_text_transfer:
        p.error("Explicit observation-text transfer authorization required")
    captures = prepare(args.case)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    order = list("AB")
    random.SystemRandom().shuffle(order)
    (args.output / "manifest.json").write_text(json.dumps({"case": args.case, "order": order,
                                                           "first_requests": captures}, indent=2))
    if args.mode == "live":
        plans = []
        for arm in order:
            row = execute(args.case, arm, expected=captures[arm], output=args.output / f"{arm}.json")
            plans.append({k: row[k] for k in ("valid", "movements", "relations", "omitted")})
        random.SystemRandom().shuffle(plans)
        ids = set(json.loads(captures["A"]["contents"][0]["parts"][0]["text"])["evidence"])
        archive = json.loads(RUN.read_text())["analysis"]["observations"]
        if args.case == "full":
            ids.update(f["observation"]["id"] for f in archive)
        evidence = {f["observation"]["id"]: {"description": f["observation"]["description"],
                                             "citation": f["citation"]} for f in archive if f["observation"]["id"] in ids}
        (args.output / "review.json").write_text(json.dumps({"plans": plans, "evidence": evidence}, indent=2))


if __name__ == "__main__":
    main()
