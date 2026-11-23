import pytest

from evaluate import QUESTIONS, evaluate
from handoff import QuestionRun
from security_augmented.contracts import VideoError


@pytest.mark.parametrize("case", ["baseline", "disjoint", "appearance", *QUESTIONS])
def test_fixed_allocation(case):
    generic, specific = (evaluate(case, enabled) for enabled in (False, True))
    assert generic["selected"] == specific["selected"]
    assert generic["supported_ids"] == specific["supported_ids"]
    assert not specific["anchor_found"]
    assert specific["completion"]["completed_checks"] == len(specific["selected"])
    branch = next(b for b in specific["schemas"][0]["anyOf"] if "relational_tasks" in b["properties"])
    assert "relational_tasks" not in branch["required"]
    assert "visual_question" in branch["properties"]["relational_tasks"]["items"]["required"]
    if case in QUESTIONS:
        assert len(specific["selected"]) == 3 and specific["displaced"] not in specific["selected"]
        assert len(specific["tasks_received"]) == len(generic["tasks_received"]) == 2
        for a, b in zip(generic["tasks_received"], specific["tasks_received"], strict=True):
            assert b == a | {"visual_question": QUESTIONS[case]}
        assert specific["frames"] == generic["frames"]
        assert specific["submitted_images"] == [4 if case == "spacing" else 2]
        assert len(specific["frames"][0]) == specific["submitted_images"][0]
        outcome, = specific["outcomes"].values()
        assert outcome["status"] == "unresolved"
        assert QUESTIONS[case] not in specific["report"]
        assert "Relational task unresolved" in specific["report"]
    else:
        assert specific["tasks_received"] == specific["frames"] == []
        assert generic["report"] == specific["report"]


def test_question_cannot_be_submitted_as_evidence():
    r = evaluate("spacing", forged=True)
    assert not r["frames"] and not r["anchor_found"]
    assert next(iter(r["outcomes"].values()))["status"] == "unresolved"
    assert QUESTIONS["spacing"] not in r["report"]


@pytest.mark.parametrize("question", ["", "The people joined.", "Did they separate?", "What changed? Why?"])
def test_malformed_question(question):
    with pytest.raises(VideoError, match="open visual question"):
        QuestionRun._relation_delegations(None, [{"observation_ids": ["a", "b"], "visual_question": question}],
                                          {}, {}, 0)
