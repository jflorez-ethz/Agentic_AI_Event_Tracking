"""Turn precomputed CAVIAR comparison packets into blank adjudication worksheets."""
import argparse
import csv
import json
from pathlib import Path

from score import HERE, artifact_hash, iou, read


def prepare(case, directory):
    packet = read(directory / f"{case}.packet.json")
    reference_dir = HERE / "caviar_references"
    reference_path = reference_dir / f"{case}.reference.json"
    if packet["case"] != case or packet["annotation_sha256"] != artifact_hash(reference_path):
        raise ValueError("Comparison packet does not match the frozen reference")
    references = {row["id"]: row for row in read(reference_path)["events"]}
    alignment = read(reference_dir / f"{case}.provenance.json")["alignment"]
    flagged = set(alignment.get("non_unique_or_closer_neighbor_indices", []))
    missing_pts = set(alignment["missing_original_pts"])
    fields = (
        "stage", "prediction_id", "predicted_start_us", "predicted_end_us", "predicted_description",
        "predicted_citation_frames", "reference_id", "caviar_object_id", "caviar_label",
        "original_start_frame", "original_end_frame_exclusive", "reference_start_us", "reference_end_us",
        "reference_frame_pts", "temporal_iou", "alignment_flags", "judgment", "review_notes",
    )
    with (directory / f"{case}.matches.csv").open("x", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for stage, predictions in packet["predictions"].items():
            for prediction in predictions:
                interval = prediction["interval"]
                cited = prediction["citations"]
                frames = {f["display_index"] for cite in cited for f in cite["frames"]}
                candidates = packet["temporal_candidates_for_review"][stage][prediction["id"]]
                for identifier in candidates or [None]:
                    row = {
                        "stage": stage, "prediction_id": prediction["id"],
                        "predicted_start_us": interval["start_us"], "predicted_end_us": interval["end_us"],
                        "predicted_description": prediction["description"],
                        "predicted_citation_frames": "; ".join(
                            f"{c['inspection_id']}: " + ",".join(
                                f"{f['display_index']}@{f['pts']}" for f in c["frames"]
                            ) for c in cited
                        ),
                    }
                    relevant_indices = set(frames)
                    if identifier is not None:
                        ref = references[identifier]
                        origin = ref["provenance"]
                        original_interval = origin["original_frame_interval"]
                        start, end = original_interval["start"], original_interval["end_exclusive"]
                        relevant_indices.update(range(start, end))
                        row.update(
                            reference_id=identifier, caviar_object_id=origin["entity_id"], caviar_label=origin["label"],
                            original_start_frame=start, original_end_frame_exclusive=end,
                            reference_start_us=ref["interval"]["start_us"], reference_end_us=ref["interval"]["end_us"],
                            reference_frame_pts=",".join(f"{f['display_index']}@{f['pts']}" for f in ref["supporting_frames"]),
                            temporal_iou=f"{iou(interval, ref['interval']):.6f}",
                        )
                    row["alignment_flags"] = "; ".join(
                        f"{label}: {','.join(map(str, sorted(relevant_indices & indices)))}"
                        for label, indices in (("neighbor ambiguity", flagged), ("missing original PTS", missing_pts))
                        if relevant_indices & indices
                    )
                    writer.writerow(row)

    draft = read(HERE / "review-template.json")
    draft.update({key: packet[key] for key in ("source_sha256", "artifact_sha256", "annotation_sha256")})
    draft["event_links"] = {stage: {row["id"]: None for row in rows} for stage, rows in packet["predictions"].items()}
    path = directory / f"{case}.review-draft.json"
    with path.open("x") as file:
        json.dump(draft, file, indent=2)
        file.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory containing the two scorer packets and no review drafts")
    args = parser.parse_args()
    for case in ("walk_split", "walk_together"):
        prepare(case, args.directory)
