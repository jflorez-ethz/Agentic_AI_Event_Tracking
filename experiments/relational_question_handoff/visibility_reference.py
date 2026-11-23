"""Compare two completed independent forms; preserve disagreements and transition brackets."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

LABELS = {"distinguishable", "not_distinguishable", "uncertain"}


def compare(manifest, first, second):
    views = manifest["views"]
    if first.samefile(second):
        raise ValueError("Supply separate reviewer forms")
    forms = []
    for path in (first, second):
        with path.open(newline="") as file:
            rows = list(csv.DictReader(file))
        if (len(rows) != len(views) or any(row["view"] != view["view"]
                or row["source_time_us"] != str(view["source_time_us"])
                or row["visibility"] not in LABELS or not row["visible_cue_or_limitation"].strip()
                for row, view in zip(rows, views))):
            raise ValueError("Incomplete, invalid or mismatched review")
        forms.append(rows)
    labels = []
    changes = []
    previous = None
    for view, a, b in zip(views, *forms, strict=True):
        label = a["visibility"] if a["visibility"] == b["visibility"] else "disagreement"
        labels.append({"view": view["view"], "first": a["visibility"], "second": b["visibility"], "status": label})
        if label not in {"uncertain", "disagreement"}:
            if previous and previous[0] != label:
                changes.append([previous[1], view["view"]])
            previous = label, view["view"]
    return {"form_sha256": [hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, second)],
            "judgments": labels, "opposite_state_brackets": changes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("manifest", "first", "second"):
        parser.add_argument(field, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.manifest.read_text()), args.first, args.second), indent=2))
