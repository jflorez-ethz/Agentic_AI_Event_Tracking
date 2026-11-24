"""Discriminating test for the TwoEnterShop1front Investigation HTTP 400 (run m1ctNI).

Arm a: the exact production Investigation request (16 visible observations, long IDs).
Arm b: the same context with observation IDs replaced by O1..On.
Text only: role instructions, schema and derived observation text. The transport allows no media
and at most two physical requests per arm. No returned action is executed; arm b's decision is
mapped back and checked by the runtime validator only.

    GOOGLE_GENAI_HTTP_CLIENT=httpx .venv/bin/python experiments/investigation_schema_ab/ab.py \
        --authorize-observation-text-transfer --output experiments/investigation_schema_ab/live-<stamp>
"""
import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

from pydantic import TypeAdapter

from security_augmented import agents
from security_augmented.agents import AgentModels, AgentRun, GeminiDecider, RoleHTTPBudget
from security_augmented.contracts import VideoError
from security_augmented.gemini import GeminiAdapter
from security_augmented.workflow import Analysis

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "experiments/TwoEnterShop1front_live.m1ctNI/run/analysis.json"
MODEL = "gemini-3.6-flash"


def load():
    data = json.loads(ARCHIVE.read_text())
    return TypeAdapter(Analysis).validate_python(data["analysis"]), data["role_calls"][0]


def new_run(analysis, decide):
    return AgentRun(analysis.video, decide, None, analysis.budget, [], autonomous_relations=True,
                    relational_selection=True, relational_tasks=True)


def production_context(analysis):
    captured = []
    new_run(analysis, lambda role, context: captured.append(context)).investigate(analysis.observations)
    return captured[0]


def aliased(context):
    alias = {identifier: f"O{n}" for n, identifier in enumerate(context["evidence"], 1)}
    return {**context, "evidence": {alias[i]: v for i, v in context["evidence"].items()}}, alias


def unalias(decision, alias):
    back = {short: long for long, short in alias.items()}
    text = json.dumps(decision)
    for short in sorted(back, key=len, reverse=True):
        text = text.replace(f'"{short}"', json.dumps(back[short]))
    return json.loads(text)


def schema_size(context):
    schema = agents._decision_schema("investigation", context)
    return len(json.dumps(schema, separators=(",", ":")))


def send(context, transport=None):
    budget = RoleHTTPBudget(2, media_limit=0)
    options = {"follow_redirects": False,
               "event_hooks": {"request": [budget.before_send], "response": [budget.after_response]}}
    if transport is not None:
        options["transport"] = transport
    adapter = GeminiAdapter.from_env(authorized=True, model=MODEL, single_request=True, client_args=options)
    model = GeminiDecider(adapter, AgentModels(MODEL, MODEL, MODEL, MODEL), http_budget=budget)
    decision = None
    with adapter.client:
        try:
            decision = model("investigation", context)
        except VideoError:
            pass
    call = {k: v for k, v in model.calls[0].items() if k not in ("decision", "raw_text")}
    return decision, call, budget


def main(argv=None, transport=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.authorize_observation_text_transfer:
        parser.error("Requires --authorize-observation-text-transfer")
    if args.output.exists():
        parser.error("Output directory already exists")
    analysis, archived_call = load()
    original = production_context(analysis)
    short, alias = aliased(original)
    args.output.mkdir(parents=True, mode=0o700)
    results = {"archive": str(ARCHIVE.relative_to(ROOT)), "archived_call": archived_call,
               "visible_observations": len(original["evidence"]), "arms": {}}
    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        for arm, context in (("a_original_ids", original), ("b_short_aliases", short)):
            decision, call, budget = send(context, transport)
            record = {"schema_bytes": schema_size(context), "call": call,
                      "physical_requests": budget.sent, "media_requests": len(budget.media_attempts)}
            if decision is not None:
                record["decision_action"] = decision.get("action")
                restored = unalias(decision, alias) if arm.startswith("b") else decision
                try:
                    ids, *_ = new_run(analysis, None)._validate_delegation(restored, analysis_visible(analysis, original))
                    record["validation"] = {"status": "accepted", "delegated_categories": [
                        next(f.observation.category for f in analysis.observations if f.observation.id == i) for i in ids]}
                except VideoError as exc:
                    record["validation"] = {"status": "rejected", "reason": str(exc)}
            results["arms"][arm] = record
            (args.output / "result.json").write_text(json.dumps(results, indent=2))
            status = call.get("http_status") or call["status"]
            print(f"{arm}: schema {record['schema_bytes']} bytes -> {status} "
                  f"{call.get('provider_message', '')!s:.200} {record.get('validation', '')}")
    return 0


def analysis_visible(analysis, context):
    return {f.observation.id: f for f in analysis.observations if f.observation.id in context["evidence"]}


if __name__ == "__main__":
    raise SystemExit(main())
