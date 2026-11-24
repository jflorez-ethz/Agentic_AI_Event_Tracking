"""Investigation short IDs and the pre-send schema bound (TwoEnterShop1front run m1ctNI, HTTP 400)."""
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from security_augmented import agents
from security_augmented.agents import INVESTIGATION_SCHEMA_BYTE_LIMIT, AgentRun
from security_augmented.contracts import VideoError
from security_augmented.workflow import PRIORITY_LABELS, Analysis, Budget, Finding

ARCHIVE = Path(__file__).resolve().parents[1] / "experiments/TwoEnterShop1front_live.m1ctNI/run/analysis.json"


def archive():
    return TypeAdapter(Analysis).validate_python(json.loads(ARCHIVE.read_text())["analysis"])


def schema_bytes(context):
    return len(json.dumps(agents._decision_schema("investigation", context), separators=(",", ":")))


def make_run(analysis, decide, *, short):
    return AgentRun(analysis.video, decide, None, replace(analysis.budget, short_observation_ids=short), [],
                    autonomous_relations=True, relational_selection=True, relational_tasks=True)


def run_with(analysis, decide, *, short, observations=None):
    run = make_run(analysis, decide, short=short)
    picks = run.investigate(tuple(observations or analysis.observations))
    return run, [f.observation.id for f in picks], run.trace


def scripted(*decisions):
    contexts = []

    def decide(role, context):
        contexts.append(context)
        return decisions[min(len(contexts), len(decisions)) - 1](context)
    return decide, contexts


def test_failed_context_becomes_the_accepted_short_schema():
    analysis = archive()
    decide, contexts = scripted(lambda c: None)
    run, _, trace = run_with(analysis, decide, short=True)
    context = contexts[0]
    assert list(context["evidence"]) == [f"O{n}" for n in range(1, 17)]
    assert schema_bytes(context) == 1877  # arm b, accepted live (investigation_schema_ab/live-20261124T025341)
    assert "observation-" not in json.dumps(context) and not any(t.action == "context_trimmed" for t in trace)


def test_short_decision_is_translated_before_validation():
    analysis = archive()
    entries = [f.observation.id for f in analysis.observations if f.observation.category == "person_enters_area"]

    def delegate(context):
        # The model only sees short labels; pick the two entries by their described category.
        ids = [k for k, v in context["evidence"].items() if v["category"] == "person_enters_area"]
        return {"action": "delegate", "reason": "Security first.", "ids": ids, "dispositions": [
            {"id": k, "status": "deferred", "reason": "Routine."} for k in context["evidence"] if k not in ids]}

    decide, contexts = scripted(delegate)
    run, picks, _ = run_with(analysis, decide, short=True)
    assert all(k.startswith("O") for k in contexts[0]["evidence"])
    assert sorted(picks) == sorted(entries)
    assert set(run.dispositions) == {f.observation.id for f in analysis.observations}  # real IDs only
    assert all(d["id"].startswith("observation-") for d in run.dispositions.values())


def test_unknown_label_is_rejected_like_an_unknown_id():
    analysis = archive()
    decide, _ = scripted(lambda c: {"action": "delegate", "reason": "Bad.", "ids": ["O99"], "dispositions": []})
    _, picks, trace = run_with(analysis, decide, short=True)
    assert picks == [] and any(t.action == "rejected" for t in trace)


def test_priority_feedback_names_short_labels():
    analysis = archive()
    routine = lambda c: {"action": "delegate", "reason": "Movements.", "ids": [
        k for k, v in c["evidence"].items() if v["category"] == "person_moved"][:4], "dispositions": [
        {"id": k, "status": "deferred", "reason": "Later."} for k, v in c["evidence"].items()
        if v["category"] != "person_moved" or k not in [
            x for x, y in c["evidence"].items() if y["category"] == "person_moved"][:4]]}
    decide, contexts = scripted(routine)
    run_with(analysis, decide, short=True)
    feedback = contexts[1]["last_tool_result"]
    assert feedback["code"] == "priority_observations_not_delegated"
    assert feedback["priority_ids"] and all(i.startswith("O") for i in feedback["priority_ids"])
    assert {contexts[1]["evidence"][i]["category"] for i in feedback["priority_ids"]} == {"person_enters_area"}


def test_unalias_covers_every_id_field():
    run = AgentRun.__new__(AgentRun)
    run.budget = Budget(short_observation_ids=True)
    run._aliases = {"observation-a": "O1", "observation-b": "O2"}
    action = run._unalias({
        "action": "delegate", "ids": ["O1"], "reason": "O1 and O2 stay in prose.",
        "dispositions": [{"id": "O2", "status": "associated", "candidate_id": "O1", "reason": "Same.",
                          "correspondence": {"id": "O2", "status": "same_event"}}],
        "relational_tasks": [{"observation_ids": ["O1", "O2"]}]})
    assert action["ids"] == ["observation-a"] and action["reason"] == "O1 and O2 stay in prose."
    assert action["dispositions"][0] | {} == {"id": "observation-b", "status": "associated",
                                              "candidate_id": "observation-a", "reason": "Same.",
                                              "correspondence": {"id": "observation-b", "status": "same_event"}}
    assert action["relational_tasks"] == [{"observation_ids": ["observation-a", "observation-b"]}]


@pytest.mark.parametrize("count", [16, 64])
def test_short_labels_fit_many_observations_without_trimming(count):
    analysis = archive()
    base = list(analysis.observations)
    many = [Finding(replace(base[n % len(base)].observation, id=f"observation-{n:064x}"), base[n % len(base)].citation)
            for n in range(count)]
    security = {f.observation.id for f in many if f.observation.category in PRIORITY_LABELS}
    decide, contexts = scripted(lambda c: None)
    run, _, trace = run_with(analysis, decide, short=True, observations=many)
    assert schema_bytes(contexts[0]) <= INVESTIGATION_SCHEMA_BYTE_LIMIT
    back = {v: k for k, v in run._aliases.items()}
    assert security <= {back[i] for i in contexts[0]["evidence"]}  # every security observation is shown
    assert not any(t.action == "context_trimmed" for t in trace)


def test_bound_hides_routine_observations_but_never_security(monkeypatch):
    analysis = archive()
    monkeypatch.setattr(agents, "INVESTIGATION_SCHEMA_BYTE_LIMIT", 1750)
    decide, contexts = scripted(lambda c: None)
    _, _, trace = run_with(analysis, decide, short=True)
    context = contexts[0]
    assert schema_bytes(context) <= 1750 and len(context["evidence"]) < 16
    assert sum(v["category"] == "person_enters_area" for v in context["evidence"].values()) == 2
    (trimmed,) = [t for t in trace if t.action == "context_trimmed"]
    assert trimmed.details == {"schema_bytes": schema_bytes(context), "limit": 1750}
    assert context["additional_evidence_available"] is True  # hidden observations stay reachable by search


def test_security_observations_are_sent_even_above_the_bound(monkeypatch):
    analysis = archive()
    monkeypatch.setattr(agents, "INVESTIGATION_SCHEMA_BYTE_LIMIT", 1000)  # below the two-entry schema
    decide, contexts = scripted(lambda c: None)
    run_with(analysis, decide, short=True)
    categories = [v["category"] for v in contexts[0]["evidence"].values()]
    assert categories.count("person_enters_area") == 2 and set(categories) == {"person_enters_area"}


def test_archived_replays_keep_their_original_request():
    analysis = archive()
    decide, contexts = scripted(lambda c: None)
    _, _, trace = run_with(analysis, decide, short=False)
    assert len(contexts[0]["evidence"]) == 16 and schema_bytes(contexts[0]) == 8939  # the request m1ctNI sent
    assert not any(t.action == "context_trimmed" for t in trace)


def test_flag_must_be_boolean():
    with pytest.raises(VideoError):
        Budget(short_observation_ids=1)
