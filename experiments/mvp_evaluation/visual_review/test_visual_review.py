import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from security_augmented.annotations import parse_annotations
from security_augmented.gemini import _png
from security_augmented.video import _decode, _frame, ingest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def cases():
    return json.loads((ROOT / "data.js").read_text().strip().removeprefix("window.REVIEW_DATA = ").removesuffix(";"))


@pytest.mark.parametrize("case_id,total", [("walk_split", 32), ("walk_together", 10)])
def test_generated_assets_match_packets_and_source(case_id, total):
    from dataclasses import asdict

    items = {item["id"]: item for item in cases()}
    item = items[case_id]
    evaluation = ROOT.parent
    packet = json.loads((evaluation / "caviar_adjudication" / f"{case_id}.packet.json").read_text())
    provenance = json.loads((evaluation / "caviar_references" / f"{case_id}.provenance.json").read_text())
    dataset = parse_annotations(REPO / provenance["local_xml"])
    video = ingest(REPO / item["source"])
    assert video.sha256 == packet["source_sha256"]
    assert sum(len(p["pairs"]) for p in item["predictions"]) == total
    mapping = {row["annotation_frame"]: row for row in provenance["frames"]}
    for prediction in item["predictions"]:
        archive = next(p for p in packet["predictions"][prediction["stage"]] if p["id"] == prediction["id"])
        assert prediction["citations"] == archive["citations"]
        assert [pair["id"] for pair in prediction["pairs"]] == packet["temporal_candidates_for_review"][prediction["stage"]][prediction["id"]]
        for pair in prediction["pairs"]:
            assert pair["frames"]
            for frame in pair["frames"]:
                row = mapping[frame["annotation_frame"]]
                assert row["display_index"] == frame["index"]
                assert row["pts"] == item["frames"][str(frame["index"])]["pts"]
                entity = next(e for e in dataset.frames[frame["annotation_frame"]].objects if e.id == pair["object_id"])
                assert frame["box"] == asdict(entity.box)
    indices = sorted(map(int, item["frames"]))
    for index, rgb in zip(indices, _decode(video, tuple(indices)), strict=True):
        frame = dict(item["frames"][str(index)])
        image = ROOT / frame.pop("image")
        assert frame == asdict(_frame(video, index, hashlib.sha256(rgb).hexdigest()))
        assert image.read_bytes() == _png(rgb, video.width, video.height)


def test_browser_logic_roundtrip_and_scorer_compatibility(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to test the static review script")
    draft, reviewed = tmp_path / "draft.json", tmp_path / "reviewed.json"
    subprocess.run([node, str(ROOT / "test_review.cjs"), str(draft), str(reviewed)], check=True, cwd=REPO)
    base = [
        sys.executable, "experiments/mvp_evaluation/score.py", "--case", "walk_split",
        "--caviar-reference", "--annotations", "experiments/mvp_evaluation/caviar_references/walk_split.reference.json",
    ]
    pending = subprocess.run([*base, "--review", str(draft)], cwd=REPO, capture_output=True, text=True)
    assert pending.returncode != 0 and "completed with known reference IDs" in pending.stderr
    completed = subprocess.run([*base, "--review", str(reviewed)], cwd=REPO, capture_output=True, text=True, check=True)
    scores = json.loads(completed.stdout)["event_scores"]
    assert scores["initial"]["tp"] == 1 and scores["verified"]["tp"] == 0
