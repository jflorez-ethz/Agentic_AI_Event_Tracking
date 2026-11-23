"""Live replay of Investigation alone over the archived LeftBox and Rest_FallOnFloor scans.

Sends only Investigation role text (instructions, schema, derived observation text, IDs and
times) to Gemini. No image, clip or Perception request can be sent: the transport media
budget is zero. Each repetition uses a fresh decider and the live-run candidate budget.

    GOOGLE_GENAI_HTTP_CLIENT=httpx .venv/bin/python experiments/investigation_priority_replay/replay.py \
        --authorize-observation-text-transfer --repeats 3 --output experiments/investigation_priority_replay/live-<stamp>
"""
import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from pydantic import TypeAdapter

from security_augmented.agents import AgentModels, AgentRun, GeminiDecider, RoleHTTPBudget
from security_augmented.gemini import GeminiAdapter
from security_augmented.workflow import Analysis, Budget

ROOT = Path(__file__).resolve().parents[2]
MODEL = "gemini-3.6-flash"
CASES = {
    "leftbox": (ROOT / "experiments/leftbox_live.qyrM8F/run/analysis.json", "object_placed"),
    "fall": (ROOT / "experiments/fall_live.spFaYl/run/analysis.json", "person_fell"),
}
# Same candidate and call budget as the archived live runs; Investigation itself uses at most two calls.
BUDGET = dict(max_initial_windows=3, max_candidates=4, max_inspections=4, max_agent_calls=14,
              max_verification_iterations=4, max_retrievals=1, max_failures=1)
PHYSICAL_PER_REPEAT = 4  # two logical Investigation calls, each with one bounded retry


def decider(transport=None):
    budget = RoleHTTPBudget(PHYSICAL_PER_REPEAT, media_limit=0)
    options = {"follow_redirects": False,
               "event_hooks": {"request": [budget.before_send], "response": [budget.after_response]}}
    if transport is not None:
        options["transport"] = transport
    adapter = GeminiAdapter.from_env(authorized=True, model=MODEL, single_request=True, client_args=options)
    return GeminiDecider(adapter, AgentModels(investigation=MODEL, verification=MODEL, reporting=MODEL, video=MODEL),
                         http_budget=budget)


def replay_once(name, transport=None):
    path, target = CASES[name]
    analysis = TypeAdapter(Analysis).validate_python(json.loads(path.read_text())["analysis"])
    categories = {f.observation.id: f.observation.category for f in analysis.observations}
    model = decider(transport)
    trace = []
    started = time.monotonic()
    with model.adapter.client:
        run = AgentRun(analysis.video, model, None, Budget(**BUDGET), trace)
        picks = [f.observation.id for f in run.investigate(analysis.observations)]
    usage = {}
    for call in model.calls:
        for key, value in dict(call.get("usage") or {}).items():
            if type(value) is int:
                usage[key] = usage.get(key, 0) + value
    return {
        "video": name, "target_category": target,
        "target_delegated": any(categories[i] == target for i in picks),
        "delegated": [{"id": i, "category": categories[i]} for i in picks],
        "feedback_round": any(t.action == "recovery" and t.actor == "investigation" for t in trace),
        "runtime_enforced": any(t.action == "priority_enforced" for t in trace),
        "dispositions": list(getattr(run, "dispositions", {}).values()),
        "investigation_trace": [asdict(t) for t in trace if t.actor == "investigation"],
        "role_calls": model.calls, "usage": usage,
        "physical_requests": model.http_budget.sent, "media_requests": len(model.http_budget.media_attempts),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def main(argv=None, transport=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.authorize_observation_text_transfer:
        parser.error("Live replay requires --authorize-observation-text-transfer")
    if args.output.exists():
        parser.error("Output directory already exists")
    args.output.mkdir(parents=True, mode=0o700)
    results = []
    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        for name in CASES:
            for repeat in range(1, args.repeats + 1):
                result = {"repeat": repeat, **replay_once(name, transport)}
                results.append(result)
                (args.output / "results.json").write_text(json.dumps(results, indent=2))
                print(f"{name} #{repeat}: target delegated={result['target_delegated']} "
                      f"feedback={result['feedback_round']} enforced={result['runtime_enforced']} "
                      f"delegated={[d['category'] for d in result['delegated']]} "
                      f"requests={result['physical_requests']} media={result['media_requests']}")
    cost = sum(r["usage"].get("prompt_token_count", 0) * 0.75e-6
               + (r["usage"].get("thoughts_token_count", 0) + r["usage"].get("candidates_token_count", 0)) * 3.75e-6
               for r in results)
    print(f"Estimated cost (USD, 2026 standard tier): {cost:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
