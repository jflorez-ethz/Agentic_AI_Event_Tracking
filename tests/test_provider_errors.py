"""A 4xx role error keeps the provider's sanitized explanation (TwoEnterShop run m1ctNI kept only the status)."""
import httpx
import pytest

from security_augmented.agents import AgentModels, GeminiDecider, RoleHTTPBudget
from security_augmented.contracts import VideoError
from security_augmented.gemini import GeminiAdapter

KEY = "AIzaSyOfflineFixtureKey0123456789abcdef"


def decider(monkeypatch, respond):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setenv("GOOGLE_GENAI_HTTP_CLIENT", "httpx")
    budget = RoleHTTPBudget(4, media_limit=0)
    adapter = GeminiAdapter.from_env(authorized=True, model="m", single_request=True, client_args={
        "transport": httpx.MockTransport(respond),
        "event_hooks": {"request": [budget.before_send], "response": [budget.after_response]}})
    return GeminiDecider(adapter, AgentModels("m", "m", "m", "m"), http_budget=budget)


def test_400_keeps_sanitized_message_and_field_violations(monkeypatch):
    def respond(request):
        return httpx.Response(400, json={"error": {
            "code": 400, "status": "INVALID_ARGUMENT",
            "message": f"The specified schema produces a constraint that has too many states for serving. "
                       f"key={KEY} near \"observation-{'a' * 64}\" in A person in a red coat waits by the door.",
            "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest", "fieldViolations": [
                {"field": "generation_config.response_json_schema", "description": "Schema too complex."}]},
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SCHEMA_TOO_COMPLEX",
                 "domain": "generativelanguage.googleapis.com"}]}})

    model = decider(monkeypatch, respond)
    with model.adapter.client, pytest.raises(VideoError):
        model("investigation", {"evidence": {"o1": {"description": "A person in a red coat waits by the door."}}})
    (call,) = model.calls
    assert call["status"] == "api_error" and call["http_status"] == 400
    message = call["provider_message"]
    assert message.startswith("The specified schema produces a constraint that has too many states for serving.")
    assert KEY not in message and "observation-" not in message and "[redacted]" in message
    assert "red coat" not in message  # request text echoed without quotes is redacted too
    assert call["provider_field_violations"] == [
        {"field": "generation_config.response_json_schema", "description": "Schema too complex."}]
    assert call["provider_error_info"] == [{"reason": "SCHEMA_TOO_COMPLEX",
                                           "domain": "generativelanguage.googleapis.com"}]
    assert call["transport_attempts"][0]["provider_message"] == message
    assert len(call["transport_attempts"]) == 1  # a 400 is not retried


def test_server_error_keeps_no_message(monkeypatch):
    def respond(request):
        return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE", "message": "Overloaded."}})

    model = decider(monkeypatch, respond)
    with model.adapter.client, pytest.raises(VideoError):
        model("investigation", {"evidence": {}})
    assert all("provider_message" not in attempt for attempt in model.calls[0]["transport_attempts"])
