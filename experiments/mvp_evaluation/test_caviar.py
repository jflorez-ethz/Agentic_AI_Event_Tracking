import json
from pathlib import Path

import pytest

from caviar import FILES, consecutive, convert
from score import HERE, read, score_events
from security_augmented.annotations import parse_annotations


@pytest.mark.parametrize("case", FILES)
def test_official_xml_conversion_reproduces_saved_reference(case):
    spec = read(HERE / "cases.json")[case]
    reference, provenance = convert(case, spec)
    saved = HERE / "caviar_references"
    assert json.loads(json.dumps(reference)) == read(saved / f"{case}.reference.json")
    assert json.loads(json.dumps(provenance)) == read(saved / f"{case}.provenance.json")
    dataset = parse_annotations(Path(spec["xml"]))
    frames = {row["annotation_frame"]: row for row in provenance["frames"]}
    for event in reference["events"]:
        origin = event["provenance"]
        start = origin["original_frame_interval"]["start"]
        assert event["category"] == "person_moved"
        assert frames[start]["source_time_us"] == event["interval"]["start_us"]
        assert origin["entity_id"] in {entity.id for entity in dataset.frames[start].objects}
    assert reference["questions"] == [] and not reference["review_complete"]
    if case == "walk_split":
        groups = {row["label"]: row for row in provenance["label_runs"]
                  if row["kind"] == "groups" and row["field"] == "situation"}
        assert groups["joining"]["members"] == ("1", "3")
        assert groups["split up"]["compatibility"] == "unmapped"
    if case == "left_bag":
        first = provenance["frames"][0]
        assert first["annotation_frame"] > 0 and first["display_index"] == first["source_time_us"] == 0
        assert len(frames) == 625
        assert any(r["label"] == "leaving object" and r["compatibility"] == "unmapped"
                   for r in provenance["label_runs"])


def test_track_gaps_do_not_create_a_continuous_event():
    assert list(consecutive([1, 2, 5, 8, 9])) == [[1, 2], [5], [8, 9]]


def test_scoring_uses_same_reviewed_link_rules_for_caviar():
    gold = read(HERE / "caviar_references/walk_split.reference.json")["events"]
    first = gold[0]
    control = {"id": "synthetic", "category": first["category"], "interval": first["interval"]}
    scored = score_events([control], gold, {"synthetic": [first["id"]]})
    assert scored["tp"] == 1 and scored["matches"][0]["iou"] == 1.0
    assert len(scored["false_negatives"]) == len(gold) - 1


def test_validation_rejects_unmapped_timestamp(tmp_path, monkeypatch):
    import sys
    import score

    reference = read(HERE / "caviar_references/walk_split.reference.json")
    reference["events"][0]["supporting_frames"][0]["source_time_us"] += 1
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(reference))
    monkeypatch.setattr(sys, "argv", ["score.py", "--case", "walk_split", "--annotations", str(path),
                                     "--caviar-reference", "--validate-only"])
    with pytest.raises(SystemExit, match="2"):
        score.main()
