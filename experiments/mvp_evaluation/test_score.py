from pathlib import Path

import pytest

from score import HERE, citation_checks, ingest, load_run, predictions, read, score_events


def row(identifier, start, end, **extra):
    return {"id": identifier, "category": "person_moved",
            "interval": {"start_us": start, "end_us": end}, **extra}


def test_matching_requires_semantic_links_and_counts_duplicates():
    refs = [row("gold", 0, 10, status="supported"), row("ambiguous", 20, 30, status="ambiguous"),
            row("missed", 40, 50, status="supported")]
    predictions = [row("p1", 0, 10), row("p2", 1, 10), row("p3", 0, 10),
                   row("p4", 20, 30), row("p5", 40, 42)]
    result = score_events(predictions, refs, {
        "p1": ["gold"], "p2": ["gold"], "p3": [], "p4": ["ambiguous"], "p5": ["missed"],
    })
    assert result["tp"] == 1
    assert result["false_positives"] == ["p2", "p3", "p5"]
    assert result["false_negatives"] == ["missed"]
    assert result["ambiguous_excluded"] == ["p4"]
    assert result["localization"]["median_iou"] == 1
    assert result["f1"] == pytest.approx(1 / 3)
    for invalid in (None, ["unknown-reference"]):
        with pytest.raises(ValueError, match="completed with known reference IDs"):
            score_events([predictions[0]], refs, {"p1": invalid})
    with pytest.raises(ValueError, match="explicit reviewed link"):
        score_events(predictions, refs, {})


@pytest.mark.parametrize("case", ["walk_split", "walk_together"])
def test_archive_ingestion_and_citation_integrity(case):
    spec = read(HERE / "cases.json")[case]
    video = ingest(Path(spec["source"]))
    analysis, execution, inspections = load_run(video, spec["artifact"])
    assert video.sha256 == spec["sha256"]
    assert execution["media_inspection_records"] >= 3
    for rows in predictions(analysis).values():
        result = citation_checks(video, rows, inspections)
        assert result["references"] and result["references"] == result["valid"]
        tampered = [{"citations": [{**rows[0]["citations"][0], "inspection_id": "unknown"}]}]
        assert citation_checks(video, tampered, inspections)["invalid"] == ["unknown"]


def test_claim_and_query_scores_keep_uncertainty_and_unfinished_checks_separate():
    from types import SimpleNamespace

    from score import score_reviews

    analysis = SimpleNamespace(
        timeline=(SimpleNamespace(observation_ids=("p1",), verdict="supported"),),
        unresolved=(SimpleNamespace(observation_ids=("p2",), verdict="insufficient"),),
        completion={"observation_dispositions": [
            {"id": "p1", "check_completed": True}, {"id": "p2", "check_completed": False},
        ]},
    )
    review = {
        "claim_reviews": [
            {"stage": "verification", "prediction_id": identifier, "reference": status,
             "claim": "Synthetic claim", "evidence_frames": [0]}
            for identifier, status in (("p1", "contradicted"), ("p2", "insufficient"))
        ],
        "report_checked": False, "report_omitted_reference_ids": [],
        "retrieval_checked": True,
        "retrieval_reviews": [{"id": "q", "outcome": "justified_abstention", "reason": "Synthetic control"}],
    }
    result = score_reviews(review, analysis, {"q"})
    assert result["verification_reference_vs_stored"] == {"contradicted/supported": 1, "insufficient/unfinished": 1}
    assert result["verification_false_support"] == {"count": 1, "denominator": 1, "rate": 1}
    assert result["retrieval"]["correct_or_justified_abstention_rate"] == 1


def test_validate_only_needs_no_model_artifact(tmp_path, monkeypatch, capsys):
    import hashlib
    import json
    import sys
    from types import SimpleNamespace

    import score

    annotation = tmp_path / "synthetic-empty-reference.json"
    annotation.write_text(json.dumps({
        "case": "synthetic", "source_sha256": "fixture", "reviewers": ["fixture"],
        "review_complete": True, "events": [], "questions": [],
    }))
    manifest = {
        "synthetic": {"source": "fixture", "sha256": "fixture", "duration_us": 1, "artifact": None},
    }
    read_file = score.read
    monkeypatch.setattr(score, "read", lambda path: manifest if path.name == "cases.json" else read_file(path))
    monkeypatch.setattr(score, "ingest", lambda _: SimpleNamespace(sha256="fixture", duration_us=1))
    monkeypatch.setattr(score, "load_run", lambda *_: pytest.fail("Validation opened a model artifact"))
    monkeypatch.setattr(sys, "argv", ["score.py", "--case", "synthetic", "--annotations", str(annotation), "--validate-only"])
    score.main()
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] and result["event_count"] == 0
    assert result["annotation_sha256"] == hashlib.sha256(annotation.read_bytes()).hexdigest()


@pytest.mark.parametrize("case", ["walk_split", "walk_together"])
def test_caviar_adjudication_worksheets_are_complete_and_blank(case, tmp_path):
    import csv
    from shutil import copyfile

    from prepare_caviar_review import prepare

    published = HERE / "caviar_adjudication"
    packet_path = tmp_path / f"{case}.packet.json"
    copyfile(published / packet_path.name, packet_path)
    prepare(case, tmp_path)
    packet = read(packet_path)
    seen = set()
    with (tmp_path / f"{case}.matches.csv").open(newline="") as source:
        for row in csv.DictReader(source):
            key = row["stage"], row["prediction_id"], row["reference_id"]
            assert key not in seen
            seen.add(key)
            assert row["predicted_citation_frames"]
            assert not row["judgment"] and not row["review_notes"]
    assert seen == {
        (stage, prediction, reference)
        for stage, rows in packet["temporal_candidates_for_review"].items()
        for prediction, references in rows.items()
        for reference in references or [""]
    }
    draft = read(tmp_path / f"{case}.review-draft.json")
    assert not draft["reviewer"]
    assert all(value is None for stage in draft["event_links"].values() for value in stage.values())
    assert (tmp_path / f"{case}.matches.csv").read_bytes() == (published / f"{case}.matches.csv").read_bytes()
