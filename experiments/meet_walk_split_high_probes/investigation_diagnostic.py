"""One authorized Investigation request with sanitized provider diagnostics."""
import argparse
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
from unittest.mock import patch

import httpx

from probe import restore, save
from security_augmented.agents import AgentModels, AgentRun, GeminiDecider, RoleHTTPBudget
from security_augmented.contracts import Video, VideoError
from security_augmented.gemini import GeminiAdapter
from security_augmented.workflow import Budget

ARCHIVE = Path(__file__).with_name("independent-relational-tasks-live") / "result.json"


def _load_evidence():
    prior = json.loads(ARCHIVE.read_text())
    scan = json.loads(Path(prior["archived_scan"]).read_text())["analysis"]
    video = Video(**(scan["video"] | {"frame_pts": tuple(scan["video"]["frame_pts"])}))
    return video, restore(scan), Budget(**prior["budget"]), AgentModels(**prior["models"])


def _run(video, budget, decide):
    return AgentRun(video, decide, None, budget, [], autonomous_relations=True,
                    relational_selection=True, relational_tasks=True)


def load_probe():
    video, initial, budget, models = _load_evidence()
    captured = []

    def capture(role, context):
        captured.append(context)
        raise VideoError("Stop before sending the reconstructed request")

    _run(video, budget, capture).investigate(initial)
    context, = captured
    return context, models


def validate_decision(decision, context):
    """Use the runtime guards without applying or dispatching the decision."""
    video, initial, budget, _ = _load_evidence()
    run = _run(video, budget, lambda *_: decision)
    action = run.action("investigation", context)
    if action is None:
        return {"status": "rejected", "reason": run.trace[-1].reason}
    try:
        if action["action"] == "delegate":
            visible = {f.observation.id: f for f in initial if f.observation.id in context["evidence"]}
            run._validate_delegation(action, visible)
        else:
            run._validate_search(action)
    except VideoError as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "accepted"}


def _strings(value):
    if isinstance(value, str):
        if len(value) >= 8:
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _sanitize(value, private):
    if not isinstance(value, str):
        return None
    for text in private:
        for form in {text, json.dumps(text, ensure_ascii=False)[1:-1], " ".join(text.split())}:
            if form:
                value = value.replace(form, "[redacted]")
    value = re.sub(r"\b(Bearer|Basic)\s+[^\s,;]+", r"\1 [redacted]", value, flags=re.I)
    value = re.sub(r"""(?i)((?:x-goog-api-key|api[-_ ]?key|access_token)\s*[:=]\s*)["']?[^\s,;"']+""",
                   r"\1[redacted]", value)
    value = re.sub(r"\bAIza[\w-]{20,}\b", "[redacted]", value)
    # Keep field-path diagnostics, but suppress any remaining quoted payload
    # fragment and long opaque values.
    value = re.sub(r"""(["'])(?:(?!\1).){1,2048}\1""", "[redacted]", value)
    value = re.sub(r"[A-Za-z0-9+/_=-]{64,}", "[redacted]", value)
    return " ".join(value.split())[:500]


def _provider_error(response, attempt, private):
    record = {"request_number": attempt, "http_status": response.status_code}
    try:
        response.read()
        payload = response.json()
    except (ValueError, OSError, httpx.HTTPError):
        return record
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return record
    if type(error.get("code")) is int:
        record["code"] = error["code"]
    if isinstance(error.get("status"), str) and re.fullmatch(r"[A-Z_]{1,40}", error["status"]):
        record["status"] = error["status"]
    if (message := _sanitize(error.get("message"), private)) is not None:
        record["message"] = message
    details = error.get("details")
    if isinstance(details, list):
        violations = []
        error_info = []
        for detail in details[:16]:
            if not isinstance(detail, dict):
                continue
            if detail.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo":
                error_info.append({key: _sanitize(detail[key], private) for key in ("reason", "domain")
                                   if isinstance(detail.get(key), str)})
            if detail.get("@type") != "type.googleapis.com/google.rpc.BadRequest":
                continue
            rows = detail.get("fieldViolations")
            if isinstance(rows, list):
                violations.extend({
                    key: _sanitize(row.get(key), private)
                    for key in ("field", "description", "reason")
                    if isinstance(row.get(key), str)
                } for row in rows[:16] if isinstance(row, dict))
        if violations:
            record["field_violations"] = violations[:16]
        if error_info:
            record["error_info"] = error_info
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-observation-text-transfer", action="store_true")
    args = parser.parse_args(argv)
    if not args.authorize_observation_text_transfer:
        parser.error("Explicit authorization to send archived observation text is required")

    context, models = load_probe()
    private = set(_strings(context))
    private.update(os.environ[key] for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY") if os.environ.get(key))
    errors = []
    budget = RoleHTTPBudget(1)
    request_metadata = {}

    def before_send(request):
        if request.url.path != f"/v1beta/models/{models.investigation}:generateContent":
            raise VideoError("Unexpected Investigation request path")
        budget.before_send(request)
        wire = request.content
        data = json.loads(wire)
        private.update(_strings(data.get("systemInstruction")))
        private.update(value for name in ("authorization", "x-goog-api-key")
                       if (value := request.headers.get(name)))
        config = data["generationConfig"]
        request_metadata.update({
            "request_number": budget.sent, "model": models.investigation, "sdk_version": version("google-genai"),
            "request_body_sha256": sha256(wire).hexdigest(), "request_body_bytes": len(wire),
            "response_mime_type": config.get("responseMimeType"),
            "max_output_tokens": config.get("maxOutputTokens"), "thinking_config": config.get("thinkingConfig"),
        })

    def after_response(response):
        budget.after_response(response)
        if response.is_error:
            errors.append(_provider_error(response, budget.sent, sorted(private, key=len, reverse=True)))

    args.output.mkdir(mode=0o700)
    with patch.dict(os.environ, {"GOOGLE_GENAI_HTTP_CLIENT": "httpx"}):
        adapter = GeminiAdapter.from_env(authorized=True, model=models.video, single_request=True, client_args={
            "follow_redirects": False,
            "event_hooks": {"request": [before_send], "response": [after_response]},
        })
        decider = GeminiDecider(adapter, models, http_budget=budget)
        decision = None
        with adapter.client:
            try:
                decision = decider("investigation", context)
            except VideoError:
                pass
    validation = (validate_decision(decision, context)
                  if decider.calls[0]["status"] == "received" else {"status": "not_reached"})
    # Keep diagnostics only. An accepted decision is never applied or persisted.
    action = decision.get("action") if isinstance(decision, dict) else None
    save(args.output, "result.json", {
        "physical_http_requests": budget.sent,
        "request": request_metadata,
        "role_call": decider.calls[0],
        "provider_errors": errors,
        "decision_action": action if action in ("search", "delegate") else None,
        "decision_validation": validation,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
