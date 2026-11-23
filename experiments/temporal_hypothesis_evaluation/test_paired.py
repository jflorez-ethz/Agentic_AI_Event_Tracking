import json
from contextlib import nullcontext
from types import SimpleNamespace

import paired
from security_augmented.observation import InferenceMetadata, ObservationResult


def test_paired_arms_lock_choices_and_offer_equal_caps(tmp_path, monkeypatch):
    output = tmp_path / "paired"
    contexts = []
    limits = []
    media = []

    class FakeDecider:
        def __init__(self, choice):
            self.choice = choice
            self.calls = []
            self.adapter = SimpleNamespace(client=nullcontext(), infer=self.infer)

        def infer(self, request):
            assert all((output / arm / "selection.json").exists() for arm in "AB")
            media.append(request)
            return ObservationResult(InferenceMetadata("mock", "fixture", None, "1", "1"), ())

        def __call__(self, role, context):
            self.calls.append({"role": role})
            if role == "investigation":
                contexts.append((context, self.temporal))
                if self.choice:
                    return {"action": "inspect", "start_us": 14_520_000, "end_us": 19_520_000, "reason": "Fixture."}
                return {"action": "abstain", "reason": "Fixture abstention."}
            if role == "verification":
                return {"outcome": "indeterminate", "tracks": [], "reason": "Fixture uncertainty."}
            return {"action": "report", "lead_id": None, "emphasis": "uncertainty", "reason": "Fixture."}

    def factory(**kwargs):
        limits.append(kwargs)
        return FakeDecider(len(limits) == 2)

    monkeypatch.setattr(paired.PairedDecider, "from_env", factory)
    assert paired.main(["--live", "--authorize-external-transfer", "--output", str(output)]) == 0
    assert contexts[0][0] == contexts[1][0]
    assert [is_temporal for _, is_temporal in contexts] == [False, True]
    assert limits[0] == limits[1] and limits[0]["max_physical_requests"] == 6
    assert len(media) == 1
    for arm in "AB":
        assert len(json.loads((output / arm / "execution-cost.json").read_text())["role_calls"]) == 2
        assert (output / arm / "verification-decision.json").exists()


def test_transport_diagnostics_and_wire_schema():
    import pytest
    from unittest.mock import Mock
    from security_augmented.contracts import VideoError

    client = Mock()
    decider = paired.PairedDecider(SimpleNamespace(client=client), paired.agents.AgentModels())
    client.models.generate_content.return_value = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")], usage_metadata=None,
    )
    with pytest.raises(VideoError, match="completed candidate"):
        decider("investigation", {})
    assert decider.calls[-1]["finish_reasons"] == ["MAX_TOKENS"]
    assert not decider.calls[-1]["completed_candidate"]
    assert decider.calls[-1]["max_output_tokens"] == 1024
    first = client.models.generate_content.call_args.kwargs["config"]
    decider.temporal = True
    client.models.generate_content.return_value = SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason="STOP")], usage_metadata=None, text="{invalid",
    )
    with pytest.raises(VideoError, match="JSON"):
        decider("investigation", {})
    second = client.models.generate_content.call_args.kwargs["config"]
    assert first["response_json_schema"] == second["response_json_schema"] == paired.SELECTION_SCHEMA
    assert second["system_instruction"] == first["system_instruction"] + paired.TEMPORAL
    assert client.models.generate_content.call_count == 2


def test_rejects_ordinary_delegation_and_exhausted_transport():
    import pytest
    from security_augmented.contracts import VideoError

    with pytest.raises(VideoError, match="must be inspect"):
        paired.selection_span({"action": "delegate", "ids": ["focus"], "reason": "Fixture"}, None, None)
    budget = paired.agents.RoleHTTPBudget(paired.LIMIT)
    budget.sent = paired.LIMIT
    budget.attempts = []
    with pytest.raises(paired.agents.PhysicalRequestLimit):
        budget.before_send(None)


def test_aftermath_rejects_reconfirmation_and_single_person(tmp_path):
    import pytest
    from security_augmented.contracts import VideoError

    focus, _ = paired.load_context(paired.ingest(paired.SOURCE))
    assert paired.assess_aftermath({"action": "verdict", "verdict": "supported"}, focus, [])["status"] == "off_topic"
    one_track = {"outcome": "divergence", "reason": "One person moved.", "tracks": [{
        "anchor_frame_id": focus.citation.frames[-1].id, "observation_id": "followup",
        "post_frame_id": "new-frame", "continuity": "One movement.",
    }]}
    with pytest.raises(VideoError, match="both people"):
        paired.assess_aftermath(one_track, focus, [])
    assert paired.assess_aftermath({"outcome": "indeterminate", "reason": "Only one person.", "tracks": []},
                                  focus, [])["outcome"] == "indeterminate"


def test_definite_aftermath_requires_grounded_post_anchor_frames():
    import pytest
    from dataclasses import replace
    from security_augmented.contracts import VideoError

    focus, _ = paired.load_context(paired.ingest(paired.SOURCE))
    anchor = focus.citation.frames[-1]
    later = replace(anchor, id="later", source_time_us=anchor.source_time_us + 1)
    witness = replace(focus, citation=replace(focus.citation, frames=(anchor, later)))
    tracks = [{"anchor_frame_id": anchor.id, "observation_id": witness.observation.id,
               "post_frame_id": later.id, "continuity": clue} for clue in ("Track on left.", "Track on right.")]
    verdict = {"outcome": "joint_continuation", "reason": "Scripted fixture.", "tracks": tracks}
    assert paired.assess_aftermath(verdict, focus, [witness])["status"] == "assessed"
    verdict["tracks"][1]["post_frame_id"] = anchor.id
    with pytest.raises(VideoError, match="post-anchor"):
        paired.assess_aftermath(verdict, focus, [witness])
