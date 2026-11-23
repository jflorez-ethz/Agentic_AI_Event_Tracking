"""Discover Gemini models and probe production role schemas with synthetic text."""

import argparse
import json
import time

from .agents import AgentModels, GeminiDecider, ROLE_HTTP_ATTEMPTS, _provider_diagnostics, _decision_schema
from .contracts import VideoError
from .gemini import GeminiAdapter

_ROLES = ("investigation", "verification")
_EVIDENCE = {
    "synthetic-1": {
        "category": "object_placed",
        "description": "Synthetic example: a toy block rests on a table in one frame.",
        "visibility_limits": "Only one synthetic frame is described.",
        "uncertainty": "The action leading to this state is unknown.",
        "inspection_id": "synthetic-inspection",
        "modality": "frames",
        "interval": {"start_us": 0, "end_us": 1_000_000},
        "frame_ids": ["synthetic-frame"],
    },
}
_CONTEXTS = {
    "investigation": {
        "evidence": _EVIDENCE, "duration_us": 2_000_000, "max_candidates": 1,
        "last_tool_result": None, "additional_evidence_available": True,
    },
    "verification": {
        "evidence": _EVIDENCE, "duration_us": 2_000_000, "candidate_id": "synthetic-1",
        "remaining_model_calls": 1, "remaining_inspections": 0, "remaining_iterations": 1,
        "last_tool_result": None, "can_inspect_and_reconsider": False,
        "validation_feedback": {"code": "missing_corroboration", "message": "Only one synthetic observation is available."},
    },
}


def _catalog():
    adapter = GeminiAdapter.from_env(authorized=True)
    started = time.monotonic()
    models = []
    result = {"sdk_version": adapter.sdk_version, "operation": "models.list", "models": models}
    with adapter.client as client:
        try:
            for model in client.models.list():
                if "generateContent" in (model.supported_actions or ()):
                    models.append({"name": model.name, "version": model.version})
        except Exception as exc:
            result.update(status="api_error", **_provider_diagnostics(exc))
        else:
            result["status"] = "complete"
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result, int(result["status"] != "complete")


def _probe(model):
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise VideoError("Install the project development extra for probe schema validation") from None

    validators = {role: Draft202012Validator(_decision_schema(role, _CONTEXTS[role])) for role in _ROLES}
    decider = GeminiDecider.from_env(
        authorized=True, models=AgentModels(investigation=model, verification=model),
        max_physical_requests=len(_ROLES) * ROLE_HTTP_ATTEMPTS,
    )
    with decider.adapter.client:
        for role in _ROLES:
            try:
                decision = decider(role, _CONTEXTS[role])
            except VideoError:
                decider.calls[-1]["schema_valid"] = None
            else:
                valid = validators[role].is_valid(decision)
                decider.calls[-1].update(
                    schema_valid=valid, status="schema_valid" if valid else "schema_invalid",
                )
    return {
        "model": model, "sdk_version": decider.adapter.sdk_version,
        "physical_http_attempts": decider.http_budget.sent,
        "role_calls": decider.calls,
    }, int(not all(call["schema_valid"] for call in decider.calls))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-models", action="store_true", help="List models advertising generateContent")
    mode.add_argument("--model", help="Send one synthetic decision request per role to this model")
    parser.add_argument("--authorize-synthetic-probe", action="store_true")
    args = parser.parse_args(argv)
    if not args.authorize_synthetic_probe:
        parser.error("Explicit authorization for Gemini catalog or synthetic requests is required")
    try:
        result, status = _catalog() if args.list_models else _probe(args.model)
    except VideoError as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
