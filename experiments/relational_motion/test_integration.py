from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from contract import Link, Mark, View
from security_augmented.agents import AgentRun, _decision_schema
from security_augmented.contracts import FrameEvidence, Interval
from security_augmented.graph_workflow import run_graph
from security_augmented.relations import Review
from security_augmented.workflow import Analysis, Budget, Citation, Finding
from security_augmented.observation import FrameReference, Observation


def fixture():
    frames = tuple(FrameEvidence(str(i), i, i, i * 500_000, str(i)) for i in range(4))
    video = SimpleNamespace(id="video", sha256="fixture", width=100, height=100, duration_us=2_000_000)
    citation = Citation("video", "frames", "frames", Interval(0, 1_000_001), frames[:3])
    obs = Observation("seed", "frames", "person_moved", "Walking.", FrameReference(("0", "1", "2")),
                      "Overlap", "Unknown identity")
    seed = Finding(obs, citation)
    later = Finding(Observation("later", "later", "person_moved", "Walked.", FrameReference(("3",)),
                               "Edge", "Local"), Citation("video", "later", "frames",
                                                         Interval(1_500_000, 1_500_001), frames[3:]))
    return video, seed, later


def replay(review, *, enabled=True, source=None, movement=False, identifier="pair"):
    video, seed, later = source or fixture()

    def decide(role, context):
        if role == "investigation":
            return dict(action="delegate", ids=[seed.observation.id], dispositions=[], reason="Review evidence.")
        if role == "reporting":
            return dict(action="report", lead_id=None, emphasis="uncertainty", reason="Report.")
        value = dict(action="verdict", verdict="insufficient", ids=[seed.observation.id], correspondence=[],
                     reason="No independent movement finding. People approached each other.")
        if movement:
            value.update(verdict="supported", transition={
                "observation_id": seed.observation.id,
                "before_frame_id": seed.citation.frames[0].id,
                "after_frame_id": seed.citation.frames[-1].id,
            })
        fields = next(branch["properties"] for branch in _decision_schema(role, context)["anyOf"]
                      if branch["properties"]["action"]["enum"] == ["verdict"])
        assert ("relation_review_id" in fields) == bool(context.get("relational_reviews"))
        if enabled:
            value["relation_review_id"] = identifier
        return value

    budget = Budget()
    trace = []
    run = AgentRun(video, decide, lambda *_: (), budget, trace,
                   relation_reviews={"pair": review} if enabled else None)
    events, report = run_graph(run, (seed,))
    event, = events
    analysis = Analysis(video, (), (seed, later),
                        tuple(e for e in events if e.verdict == "supported"),
                        tuple(e for e in events if e.verdict != "supported"), tuple(trace), report, budget)
    return event, analysis


def test_validated_approach_survives_graph_report_and_retrieval():
    review = Review("approach", Interval(0, 500_001), (
        View("0", (Mark(10, 50, 1), Mark(80, 50, 1))),
        View("1", (Mark(30, 50, 1), Mark(65, 50, 1))),
    ))
    event, analysis = replay(review)
    assert event.verdict == "insufficient"
    assert asdict(event)["relation"]["status"] == "supported"
    assert "Apparent convergence" in analysis.report
    assert analysis.ask("What happened after the two people approached each other?").anchor is not None
    assert analysis.ask("What happened after the same people separated?").anchor is None
    assert replay(review, enabled=False)[1].ask("What happened after the two people approached each other?").anchor is None


def separation(views):
    return Review("separation", Interval(0, 1_000_001), views, True, "0",
                  tuple(Link(a.frame_id, b.frame_id, (0, 1)) for a, b in zip(views, views[1:])))


def test_synthetic_two_way_links_and_overlap():
    entries = (
        View("0", (Mark(40, 50, 1), Mark(55, 50, 1))),
        View("1", (Mark(25, 50, 1), Mark(65, 50, 1))),
        View("2", (Mark(10, 50, 1), Mark(80, 50, 1))),
    )
    query = "What happened after the same two people separated?"
    event, analysis = replay(separation(entries))
    assert event.relation.continuity == "reviewed"
    assert analysis.ask(query).anchor == event.relation
    for views in ((entries[0], View("1", None), entries[2]), (entries[0], entries[2])):
        event, analysis = replay(separation(views))
        assert event.relation.status == "insufficient"
        assert "Relationship unresolved" in analysis.report
        assert analysis.ask(query).anchor is None
    incomplete = replace(separation(entries), links=separation(entries).links[:1])
    assert replay(incomplete)[0].relation.status == "insufficient"


@pytest.mark.parametrize(("claim", "interval", "frame_id", "identifier"), [
    ("joining", Interval(0, 500_001), "1", "pair"),
    ("approach", Interval(0, 500_005), "1", "pair"),
    ("approach", Interval(0, 500_001), "bogus", "pair"),
    ("approach", Interval(0, 500_001), "1", "unknown-review"),
])
def test_invalid_relation_preserves_supported_movement(claim, interval, frame_id, identifier):
    video, seed, later = fixture()
    review = Review(claim, interval, (
        View("0", (Mark(10, 50, 1), Mark(80, 50, 1))),
        View(frame_id, (Mark(30, 50, 1), Mark(65, 50, 1))),
    ))
    event, analysis = replay(review, identifier=identifier, movement=True, source=(video, seed, later))
    baseline, _ = replay(review, enabled=False, movement=True, source=(video, seed, later))
    assert event == baseline
    assert event.verdict == "supported"
    assert event.relation is None
    assert any(row.action == "relation_rejected" for row in analysis.trace)
    for phrase in ("the two people approached each other", "the two people joined", "the two people were near each other"):
        assert analysis.ask(f"What happened after {phrase}?").anchor is None


def test_ambiguous_anchors_remain_ambiguous():
    review = Review("approach", Interval(0, 500_001), (
        View("0", (Mark(10, 50, 1), Mark(80, 50, 1))),
        View("1", (Mark(30, 50, 1), Mark(65, 50, 1))),
    ))
    event, analysis = replay(review)
    another = replace(event, relation=replace(event.relation, review_id="another"))
    answer = replace(analysis, unresolved=(event, another)).ask("What happened after apparent convergence?")
    assert answer.anchor is None
    assert "Several grounded events" in answer.text


def test_nearby_is_a_single_view_relation_and_cannot_anchor_joining():
    review = Review("nearby", Interval(500_000, 500_001),
                    (View("1", (Mark(30, 50, 1), Mark(45, 50, 1))),), nearby_frame_id="1")
    event, analysis = replay(review)
    assert sum(len(c.frames) for c in event.relation.citations) == 1
    assert analysis.ask("What happened after the people were near each other?").anchor == event.relation
    assert analysis.ask("What happened after the people walked together?").anchor is None


def test_supported_approach_has_its_own_interval_and_citations_in_direct_queries():
    review = Review("approach", Interval(0, 500_001), (
        View("0", (Mark(10, 50, 1), Mark(80, 50, 1))),
        View("1", (Mark(30, 50, 1), Mark(65, 50, 1))),
    ))
    movement, analysis = replay(review)
    assert movement.verdict == "insufficient"
    for query in ("Did the two people approach each other?",
                  "Did the two people approach each other between 0 and 1 seconds?",
                  "What happened between 0 and 1 seconds?"):
        event, = analysis.ask(query).events
        assert event.category == "relational_task"
        assert event.interval == review.interval
        assert event.citations == movement.relation.citations
    assert "continuity remains unresolved" in analysis.ask("Show apparent convergence").text
    assert not analysis.ask("Did the two people approach each other between 1 and 2 seconds?").events
    assert not analysis.ask("Did the two people approach each other and walk together?").events


def test_supported_movement_cannot_answer_an_unverified_relationship_question():
    review = Review("approach", Interval(0, 500_001), (
        View("0", (Mark(10, 50, 1), Mark(80, 50, 1))),
        View("1", (Mark(30, 50, 1), Mark(65, 50, 1))),
    ))
    _, analysis = replay(review, enabled=False, movement=True)
    assert analysis.ask("Did a person move?").events
    for question in ("Did a person follow the other person?", "Did the two people approach each other?",
                     "Did the two people walk together?", "Did the same two people separate?"):
        answer = analysis.ask(question)
        assert not answer.events and "Insufficient" in answer.text
