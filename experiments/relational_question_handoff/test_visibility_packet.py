import csv
import hashlib
import json

from PIL import Image
import pytest

from visibility_packet import prepare
from visibility_reference import compare


def test_packet(tmp_path):
    folder = tmp_path / "packet"
    m = prepare(folder)
    assert sum(v["original_citation"] for v in m["views"]) == 13 and len(m["views"]) == 25
    for win in m["reference_windows"]:
        interval = win["requested_interval"]
        assert interval["end_us"] - interval["start_us"] <= 5000000 and len(win["frames"]) <= 20
    review = folder / "reviewer"
    with Image.open(review/"views.png") as sheet:
        w, h = m["reference_windows"][0]["frame_size"]
        for i, v in enumerate(m["views"]):
            x, y = i%4*w, i//4*(h+24)
            assert hashlib.sha256(sheet.crop((x,y,x+w,y+h)).tobytes()).hexdigest() == v["rgb24_sha256"]
    a, b = (review/f"reviewer-{n}.csv" for n in (1,2))
    with pytest.raises(ValueError, match="Incomplete"):
        compare(m, a, b)
    # Synthetic labels exercise the scoring rule exclusively in temporary files.
    for n, p in enumerate((a, b)):
        with p.open() as f:
            rows = list(csv.DictReader(f))
        for i, row in enumerate(rows):
            row.update(visibility="distinguishable" if i == 0 or i == 1 and n else "not_distinguishable",
                       visible_cue_or_limitation="synthetic")
        with p.open("w", newline="") as f:
            writer = csv.DictWriter(f, rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    out = compare(m, a, b)
    assert out["judgments"][1]["status"] == "disagreement"
    assert out["opposite_state_brackets"] == [["V01","V03"]]
    body = json.loads((folder/"specific.json").read_text())
    ctx = json.loads(body["contents"][0]["parts"][0]["text"])
    assert ctx["fine_available"] and ctx["remaining_inspections"] == 4
    assert ctx["last_tool_result"] is None and ctx["relational_proposals"] == {}
    assert set(ctx["evidence"]) == set(m["members"])
