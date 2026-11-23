"""Convert pinned local CAVIAR XML copies into evaluation-only movement references."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path

from score import HERE, artifact_hash, read
from security_augmented.annotations import align_leftbag, parse_annotations
from security_augmented.contracts import ClipFrame, ClipInspection, FrameEvidence, Interval
from security_augmented.video import _run, ingest, validate_clip

FILES = {
    "walk_split": ("Meet_WalkSplit", "mws1gt.xml", "a3f76c5f9539d9bff4730863d503ce979c5dfe5e9595689578eedd4d6bbd790b"),
    "walk_together": ("Meet_WalkTogether1", "mwt1gt.xml", "cb8cdb35b04c590503e25a5ef3b9fb96eedb90a9e3af3208caa3cbc35ae63092"),
    "left_bag": ("LeftBag", "lb1gt.xml", "9599de02b41369065f1c718ec9c934bf1d58b65dc969b88e36c08ca54ab52bb7"),
}
URL = "https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1"


def compare_presentation_order(original, local):
    """Compare decoded luma content against nearby indices after lossy conversion."""
    size = 96 * 72

    def luma(path):
        raw = _run("ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
                   "-vf", "scale=96:72,format=gray,setpts=N", "-fps_mode", "passthrough",
                   "-f", "rawvideo", "-").stdout
        if len(raw) % size:
            raise ValueError("Incomplete frame in luma comparison")
        return [raw[i:i + size] for i in range(0, len(raw), size)]

    a, b = luma(original), luma(local.source_path)
    if not len(a) == len(b) == len(local.frame_pts):
        raise ValueError("Presentation frame counts differ")

    def error(x, y):
        return sum(abs(i - j) for i, j in zip(x, y, strict=True)) / size

    same = [error(frame, b[i]) for i, frame in enumerate(a)]
    exceptions = [i for i, frame in enumerate(a) if any(
        error(frame, b[j]) <= same[i] for j in range(max(0, i - 2), min(len(b), i + 3)) if j != i
    )]
    if max(same) > 1 or len(exceptions) / len(same) > .01:
        raise ValueError("Local presentation-order alignment did not pass the luma check")
    return {"frames": len(a), "same_index_mean_absolute_luma_error": sum(same) / len(same),
            "same_index_max_absolute_luma_error": max(same), "non_unique_or_closer_neighbor_indices": exceptions}


def frame_mapping(case, spec, dataset, video, sequence):
    original_path = Path(spec.get("original_source", f"data/raw/{sequence}.mpg"))
    original_probe = json.loads(_run(
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_streams",
        "-show_entries", "frame=pts:stream=time_base", "-of", "json", str(original_path),
    ).stdout)
    original_pts = [row.get("pts") for row in original_probe["frames"]]
    if (len(original_pts) != len(dataset.frames) + 1
            or dataset.frames[0].number != 0 or dataset.frames[-1].number != len(dataset.frames) - 1):
        raise ValueError("Unexpected original or annotation frame count")
    if case == "left_bag":
        original = ingest(original_path)
        align_leftbag(dataset, original)
        raw = read(spec["original_frame_map"])["inspection"]
        inspection = ClipInspection(**{
            **raw,
            "requested_interval": Interval(**raw["requested_interval"]),
            "actual_source_interval": Interval(**raw["actual_source_interval"]),
            "frames": tuple(ClipFrame(FrameEvidence(**f["source"]), f["clip_pts"]) for f in raw["frames"]),
        })
        validate_clip(original, inspection, Path(spec["source"]).read_bytes())
        mapping = {f.source.display_index: i for i, f in enumerate(inspection.frames)}
        if tuple(f.clip_pts for f in inspection.frames) != video.frame_pts:
            raise ValueError("Excerpt PTS differs from recorded mapping")
        details = {"method": "checked original XML and pixel-identical excerpt map",
                   "clip_inspection_id": inspection.id}
    else:
        details = {"method": "same-index luma comparison against local original MPEG",
                   **compare_presentation_order(original_path, video)}
        mapping = {i: i for i in range(len(dataset.frames))}
    if any(i < 0 or i >= len(dataset.frames) or j < 0 or j >= len(video.frame_pts)
           for i, j in mapping.items()) or len(set(mapping.values())) != len(mapping):
        raise ValueError("Out-of-range or duplicate mapped frame")
    rows = [{
        "annotation_frame": index, "original_pts": original_pts[index], "display_index": local,
        "pts": video.frame_pts[local], "source_time_us": int(video.time_at_pts(video.frame_pts[local]) * 1_000_000),
    } for index, local in mapping.items()]
    return rows, {**details, "original_sha256": artifact_hash(original_path), "original_frames": len(original_pts),
                  "missing_original_pts": [i for i, pts in enumerate(original_pts) if pts is None],
                  "original_time_base": original_probe["streams"][0]["time_base"],
                  "local_time_base": str(video.time_base),
                  "local_frames": len(video.frame_pts), "unlabelled_original_indices": [len(dataset.frames)]}


def consecutive(indices):
    span = []
    for index in indices:
        if span and index != span[-1] + 1:
            yield span
            span = []
        span.append(index)
    if span:
        yield span


def label_inventory(dataset, mapped_frames, width, height):
    ids, indices, flags = defaultdict(set), defaultdict(list), Counter()
    for frame in dataset.frames:
        present = {e.id for e in frame.objects}
        for kind in ("objects", "groups"):
            seen = set()
            for entity in getattr(frame, kind):
                if entity.id in seen:
                    flags["duplicate_entity_id_in_frame"] += 1
                seen.add(entity.id)
                ids[kind].add(entity.id)
                box = entity.box
                if not (0 <= box.xc < width and 0 <= box.yc < height):
                    flags["box_center_outside_image"] += 1
                if (box.xc - box.width / 2 < 0 or box.xc + box.width / 2 > width
                        or box.yc - box.height / 2 < 0 or box.yc + box.height / 2 > height):
                    flags["box_extends_outside_image"] += 1
                if kind == "groups" and (not entity.members or set(entity.members) - present):
                    flags["group_missing_member_in_frame"] += 1
                if frame.number not in mapped_frames:
                    continue
                for hypothesis in entity.hypotheses:
                    fields = [(k, v, ev) for k, v, ev in hypothesis.fields]
                    if entity.appearance:
                        fields.append(("appearance", entity.appearance, None))
                    for field, value, evaluation in fields:
                        key = (kind, entity.id, entity.members, hypothesis.id, field, value, evaluation)
                        indices[key].append(frame.number)
    return {kind: sorted(values) for kind, values in ids.items()}, indices, dict(flags)


def convert(case, spec):
    sequence, filename, expected_digest = FILES[case]
    dataset = parse_annotations(Path(spec["xml"]))
    video = ingest(Path(spec["source"]))
    if (dataset.sha256 != expected_digest or dataset.name != sequence
            or video.sha256 != spec["sha256"] or video.duration_us != spec["duration_us"]):
        raise ValueError("Inputs do not match the pinned evaluation assets")
    mapping, alignment = frame_mapping(case, spec, dataset, video, sequence)
    indexed = {row["annotation_frame"]: row for row in mapping}
    ids, labels, qc = label_inventory(dataset, indexed, video.width, video.height)
    events, original_labels = [], []

    def point(index):
        row = indexed[index]
        return {field: row[field] for field in ("display_index", "pts", "source_time_us")}

    for (kind, identifier, members, hypothesis, field, label, evaluation), indices in labels.items():
        for run in consecutive(sorted(set(indices))):
            start, last = run[0], run[-1]
            local_end = indexed[last]["display_index"] + 1
            end = (int(video.time_at_pts(video.frame_pts[local_end]) * 1_000_000)
                   if local_end < len(video.frame_pts) else video.duration_us)
            interval = Interval(point(start)["source_time_us"], end)
            interval.validate(video.duration_us)
            compatible = kind == "objects" and field == "movement" and label == "walking"
            provenance = {
                "xml": spec["xml"], "kind": kind, "entity_id": identifier, "members": members,
                "hypothesis_id": hypothesis, "field": field, "label": label, "field_evaluation": evaluation,
                "original_frame_interval": {"start": start, "end_exclusive": last + 1},
                "local_interval": asdict(interval),
                "compatibility": "broader_person_moved" if compatible else "unmapped",
            }
            original_labels.append(provenance)
            if compatible:
                events.append({
                    "id": f"caviar-person-{identifier}-{start}-{last}", "category": "person_moved",
                    "description": f"CAVIAR labels individual {identifier} walking.", "interval": asdict(interval),
                    "status": "supported", "participants": [f"caviar-object:{identifier}"],
                    "supporting_frames": [point(i) for i in dict.fromkeys((start, last))],
                    "uncertainty": "Label boundaries follow the XML, clipped to the evaluation source.",
                    "provenance": provenance,
                })
    labels_by_kind = {kind: sorted({f"{row['field']}={row['label']}" for row in original_labels if row["kind"] == kind})
                      for kind in ids}
    return {
        "case": case, "source_sha256": video.sha256, "reference_kind": "caviar_conversion",
        "alignment_status": "local_verified", "review_complete": False, "reviewers": [],
        "events": sorted(events, key=lambda e: (e["interval"]["start_us"], e["id"])), "questions": [],
    }, {
        "sequence": sequence, "local_xml": spec["xml"], "original_filename": filename,
        "official_url": f"{URL}/{sequence}/{filename}", "xml_sha256": dataset.sha256,
        "publisher_bytes_rechecked": False, "annotated_frames": len(dataset.frames), "ids": ids,
        "alignment": alignment, "quality_control": qc, "frames": mapping,
        "labels_by_kind_in_scope": labels_by_kind, "label_runs": original_labels,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir()
    for case, spec in read(HERE / "cases.json").items():
        reference, provenance = convert(case, spec)
        for suffix, data in (("reference", reference), ("provenance", provenance)):
            (args.output / f"{case}.{suffix}.json").write_text(json.dumps(data, indent=2) + "\n")
        print(case, len(reference["events"]), "walking runs;", len(provenance["label_runs"]), "original label runs")


if __name__ == "__main__":
    main()
