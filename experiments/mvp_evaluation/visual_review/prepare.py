"""Build the local review assets from the frozen comparison packets."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from score import HERE, artifact_hash, iou, read
from security_augmented.annotations import parse_annotations
from security_augmented.gemini import _png
from security_augmented.video import _decode, _frame, ingest


def representative(items):
    if len(items) <= 5:
        return items
    return [items[i * (len(items) - 1) // 4] for i in range(5)]


def build_case(case, spec, out):
    packet = read(HERE / "caviar_adjudication" / f"{case}.packet.json")
    reference = HERE / "caviar_references" / f"{case}.reference.json"
    provenance = read(HERE / "caviar_references" / f"{case}.provenance.json")
    references = {r["id"]: r for r in read(reference)["events"]}
    video = ingest(Path(spec["source"]))
    dataset = parse_annotations(Path(spec["xml"]))
    if (packet["annotation_sha256"] != artifact_hash(reference) or packet["source_sha256"] != video.sha256
            or video.sha256 != spec["sha256"] or provenance["xml_sha256"] != dataset.sha256):
        raise ValueError("Comparison packet, references, XML and source must match")
    local = {f["annotation_frame"]: f for f in provenance["frames"]}
    alignment = provenance["alignment"]
    flagged = set(alignment.get("non_unique_or_closer_neighbor_indices", []))
    missing = set(alignment["missing_original_pts"])
    requests, groups = {}, []

    def request(index, expected=None):
        if expected is not None:
            prior = requests.get(index)
            if prior is not None and prior != expected:
                raise ValueError("Conflicting citation hashes for the same display index")
            requests[index] = expected
        else:
            requests.setdefault(index, None)
        return index

    for stage, predictions in packet["predictions"].items():
        for prediction in predictions:
            cited = sorted({f["display_index"]: f for c in prediction["citations"] for f in c["frames"]}.values(),
                           key=lambda f: f["display_index"])
            for frame in cited:
                request(frame["display_index"], frame)
            pairs = []
            for identifier in packet["temporal_candidates_for_review"][stage][prediction["id"]]:
                ref = references[identifier]
                origin = ref["provenance"]
                object_id = origin["entity_id"]
                bounds = origin["original_frame_interval"]
                indices = range(bounds["start"], bounds["end_exclusive"])
                overlap_start = max(prediction["interval"]["start_us"], ref["interval"]["start_us"])
                overlap_end = min(prediction["interval"]["end_us"], ref["interval"]["end_us"])
                selected = representative([i for i in indices if i in local and
                                           overlap_start <= local[i]["source_time_us"] < overlap_end])
                samples, warnings = [], []
                missing_count = sum(i not in local for i in indices)
                if missing_count:
                    warnings.append(f"{missing_count} reference frames are missing from the local alignment.")
                for i in selected:
                    row = local[i]
                    index = row["display_index"]
                    if (not 0 <= index < len(video.frame_pts) or video.frame_pts[index] != row["pts"]
                            or int(video.time_at_pts(row["pts"]) * 1_000_000) != row["source_time_us"]):
                        warnings.append(f"Annotation frame {i} has no reliable local mapping.")
                        continue
                    entity = next((e for e in dataset.frames[i].objects if e.id == object_id), None)
                    if entity is None:
                        warnings.append(f"Object {object_id} has no box at annotation frame {i}.")
                        continue
                    samples.append({"index": request(index), "annotation_frame": i, "box": asdict(entity.box)})
                if not samples:
                    warnings.append("No reliable reference images could be recovered in the overlap.")
                relevant = set(indices) | {f["display_index"] for f in cited}
                for label, affected in (("Near-neighbor alignment flag", flagged), ("Missing original MPEG PTS", missing)):
                    if relevant & affected:
                        warnings.append(f"{label}: {', '.join(map(str, sorted(relevant & affected)))}.")
                pairs.append({"id": ref["id"], "object_id": object_id, "label": origin["label"], "interval": ref["interval"],
                              "frames": samples, "iou": iou(prediction["interval"], ref["interval"]), "warnings": warnings})
            groups.append({"stage": stage, **prediction, "frames": [f["display_index"] for f in cited], "pairs": pairs})

    destination = out / case
    destination.mkdir(parents=True, exist_ok=True)
    frames = {}
    indices = sorted(requests)
    for index, rgb in zip(indices, _decode(video, tuple(indices)), strict=True):
        frame = asdict(_frame(video, index, hashlib.sha256(rgb).hexdigest()))
        if requests[index] is not None and requests[index] != frame:
            raise ValueError(f"Cited frame {index} differs from recorded provenance")
        name = f"{index}.png"
        (destination / name).write_bytes(_png(rgb, video.width, video.height))
        frames[index] = {**frame, "image": f"assets/{case}/{name}"}
    return {
        "id": case, "name": dataset.name, "source": spec["source"], "width": video.width, "height": video.height,
        "frames": frames, "predictions": groups,
        "draft": read(HERE / "caviar_adjudication" / f"{case}.review-draft.json"),
        "alignment": {"flagged_indices": sorted(flagged), "missing_original_pts": sorted(missing)},
    }


def main():
    specs = read(HERE / "cases.json")
    data = [build_case(case, specs[case], ROOT / "assets") for case in ("walk_split", "walk_together")]
    (ROOT / "data.js").write_text("window.REVIEW_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")


if __name__ == "__main__":
    main()
