"""Local scoring of frozen video outputs and separately reviewed references."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from statistics import mean, median
from pathlib import Path

from security_augmented.contracts import FrameEvidence, Interval
from security_augmented.observation import ClipReference, FrameReference, Observation
from security_augmented.video import _decode, _frame, ingest
from security_augmented.workflow import Analysis, ArchivedInspection, Budget, Citation, Event, Finding, InspectionPlan, _video_coverage

HERE = Path(__file__).resolve().parent
THRESHOLD = 0.30


def read(path):
    return json.loads(Path(path).read_text())


def artifact_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def citation(row):
    return Citation(row["video_id"], row["inspection_id"], row["modality"], Interval(**row["interval"]),
                    tuple(FrameEvidence(**f) for f in row["frames"]))


def event(row):
    return Event(row["category"], Interval(**row["interval"]), row["verdict"], row["reason"],
                 tuple(row["observation_ids"]), tuple(map(citation, row["citations"])))


def finding(row):
    obs, cite = row["observation"], citation(row["citation"])
    evidence = obs["evidence"]
    reference = (
        FrameReference(tuple(evidence["frame_ids"])) if "frame_ids" in evidence
        else ClipReference(Interval(**evidence["interval"]))
    )
    return Finding(Observation(obs["id"], obs["inspection_id"], obs["category"], obs["description"], reference,
                               obs["visibility_limits"], obs["uncertainty"]), cite)


def usage(records):
    totals, known = Counter(), Counter()
    for record in records:
        totals.update(record)
        known.update(record.keys())
    return {"records": len(records), "totals": dict(totals), "records_with_field": dict(known)}


def load_run(video, path):
    run = read(path)
    if "analysis" in run:
        scan = run["analysis"]
        rows = scan["timeline"] + scan["unresolved"]
        targeted = [row for row in scan["evidence"] if row.get("phase") == "targeted"]
        digest = scan["video"]["sha256"]
        completion = scan.get("completion")
        media_attempts = None  # This artifact does not separately log physical media sends.
    else:
        scan = read(run["archived_scan"])["analysis"]
        rows = run["events"]
        targeted = run["targeted_evidence"]
        digest = run["source_sha256"]
        completion = run["completion"]
        media_attempts = len(run["media_attempts"])  # Targeted segment only.
    if digest != video.sha256 or scan["video"]["sha256"] != digest:
        raise ValueError("Artifact, scan and source hashes must agree")
    initial = tuple(map(finding, scan["observations"]))
    events = tuple(map(event, rows))
    report_path = Path(path).with_name("report.md")
    report = report_path.read_text() if report_path.is_file() else scan.get("report", "")
    media = [row for row in scan["evidence"] if row.get("phase") == "initial"] + targeted
    roles = run.get("role_calls", [])
    stats = {
        "models": run.get("models"), "completion": completion,
        "role_calls": len(roles),
        "role_physical_attempts": sum(len(r["transport_attempts"]) for r in roles)
        if roles and all("transport_attempts" in r for r in roles) else None,
        "targeted_media_attempts_logged": media_attempts,
        "media_inspection_records": len(media),
        "role_usage": usage([r.get("usage", {}) for r in roles]),
        "media_usage": usage([dict((r.get("inference") or {}).get("usage", [])) for r in media]),
        "role_elapsed_ms": [r.get("elapsed_ms") for r in roles],
        "media_elapsed_ms": [(r.get("inference") or {}).get("elapsed_ms") for r in media],
        "wall_seconds": run.get("wall_seconds"),
        "media_status_counts": dict(Counter(row["status"] for row in media)),
        "media_settings": [(row.get("inference") or {}).get("settings") for row in media],
        "role_settings": [{k: r.get(k) for k in ("role", "model", "thinking_level", "max_output_tokens")} for r in roles],
        "scan_coverage": scan.get("coverage"),
    }
    archived_evidence = tuple(ArchivedInspection(
        row["path"], row["modality"], Interval(**row["interval"]), row["status"],
        tuple(map(finding, row["findings"])), coverage=tuple(Interval(**span) for span in row.get("coverage", [])),
        phase=row.get("phase"),
    ) for row in media)
    coverage = scan.get("coverage")
    coverage = _video_coverage(
        video, archived_evidence, InspectionPlan(**coverage["plan"]), coverage["initial_scan"],
        coverage["initial_scan_end_us"],
    ) if coverage else None
    inspections = {}
    for row in media:
        inspection = row.get("inspection")
        if row["status"] == "success" and inspection:
            inspections[inspection["id"]] = (
                row["modality"], {f.get("source", f)["id"] for f in inspection["frames"]},
            )
    return Analysis(video, archived_evidence, initial, tuple(e for e in events if e.verdict == "supported"),
                    tuple(e for e in events if e.verdict != "supported"), (), report, Budget(),
                    completion, coverage), stats, inspections


def predictions(analysis):
    return {
        "initial": [{
            "id": f.observation.id, "category": f.observation.category,
            "interval": asdict(f.citation.interval), "description": f.observation.description,
            "citations": [asdict(f.citation)],
        } for f in analysis.observations if f.observation.category != "insufficient_evidence"],
        "verified": [{
            "id": e.observation_ids[0], "category": e.category, "interval": asdict(e.interval),
            "description": e.reason, "citations": list(map(asdict, e.citations)),
        } for e in analysis.timeline],
    }


def iou(a, b):
    start, end = max(a["start_us"], b["start_us"]), min(a["end_us"], b["end_us"])
    union = max(a["end_us"], b["end_us"]) - min(a["start_us"], b["start_us"])
    return max(0, end - start) / union


def score_events(rows, references, links):
    """Greedy one-to-one assignment, after human adjudication of semantic compatibility."""
    if set(links) != {row["id"] for row in rows}:
        raise ValueError("Every prediction needs an explicit reviewed link list, including unmatched predictions")
    gold = {r["id"]: r for r in references}
    for proposed in links.values():
        if not isinstance(proposed, list) or any(not isinstance(key, str) or key not in gold for key in proposed):
            raise ValueError("Each reviewed link list must be completed with known reference IDs")
    positive = {identifier for identifier, r in gold.items() if r["status"] == "supported"}
    edges, ambiguous = [], set()
    for row in rows:
        identifier = row["id"]
        for key in links[identifier]:
            ref = gold[key]
            overlap = iou(row["interval"], ref["interval"])
            if row["category"] == ref["category"] and overlap >= THRESHOLD:
                if key in positive:
                    edges.append((-overlap, identifier, key))
                else:
                    ambiguous.add(identifier)
    matches = []
    used_predictions, used_references = set(), set()
    by_id = {row["id"]: row for row in rows}
    for negative_iou, prediction, reference in sorted(edges):
        if prediction in used_predictions or reference in used_references:
            continue
        used_predictions.add(prediction)
        used_references.add(reference)
        a, b = by_id[prediction]["interval"], gold[reference]["interval"]
        matches.append({"prediction": prediction, "reference": reference, "iou": -negative_iou,
                        "start_error_us": abs(a["start_us"] - b["start_us"]),
                        "end_error_us": abs(a["end_us"] - b["end_us"])})
    # A duplicate positive stays an FP even if it also overlaps an ambiguous reference.
    ignored = ambiguous - {prediction for _, prediction, _ in edges}
    fp = set(by_id) - used_predictions - ignored
    fn = positive - used_references
    localization = {
        "median_iou": median(m["iou"] for m in matches) if matches else None,
        "mean_start_error_us": mean(m["start_error_us"] for m in matches) if matches else None,
        "mean_end_error_us": mean(m["end_error_us"] for m in matches) if matches else None,
    }
    return {"tp": len(matches), "false_positives": sorted(fp), "false_negatives": sorted(fn),
            "ambiguous_excluded": sorted(ignored), "matches": matches, "localization": localization,
            "precision": len(matches) / (len(matches) + len(fp)) if matches or fp else None,
            "recall": len(matches) / len(positive) if positive else None,
            "f1": 2 * len(matches) / (2 * len(matches) + len(fp) + len(fn)) if matches or fp or fn else None}


def citation_checks(video, records, inspections):
    citations = [cite for row in records for cite in row["citations"]]
    indices = sorted({f["display_index"] for c in citations for f in c["frames"]
                      if 0 <= f["display_index"] < len(video.frame_pts)})
    decoded = dict(zip(indices, _decode(video, tuple(indices)), strict=True)) if indices else {}
    hashes = {i: hashlib.sha256(rgb).hexdigest() for i, rgb in decoded.items()}

    def frame_valid(f, bounds):
        index = f["display_index"]
        return (index in hashes and asdict(_frame(video, index, hashes[index])) == f
                and bounds["start_us"] <= f["source_time_us"] < bounds["end_us"])

    invalid = []
    for cite in citations:
        modality, frame_ids = inspections.get(cite["inspection_id"], (None, set()))
        if (cite["video_id"] != video.id or cite["modality"] != modality or not cite["frames"]
                or any(f["id"] not in frame_ids or not frame_valid(f, cite["interval"]) for f in cite["frames"])):
            invalid.append(cite["inspection_id"])
    return {"references": len(citations), "valid": len(citations) - len(invalid), "invalid": invalid}


def score_reviews(review, analysis, question_ids):
    labels = {"supported", "contradicted", "insufficient"}
    verification = Counter()
    initial = Counter()
    report = Counter()
    for row in review["claim_reviews"]:
        label = row["reference"]
        if label not in labels or not row["claim"] or not row["evidence_frames"]:
            raise ValueError("Atomic claim reviews require a reference judgment and source frames")
        if row["stage"] == "verification":
            # Claim judgments are mapped to the stored event verdict rather than accepting a second verdict from the reviewer.
            matches = [e for e in (*analysis.timeline, *analysis.unresolved)
                       if e.observation_ids[0] == row["prediction_id"]]
            if len(matches) != 1:
                raise ValueError("Verification claim needs a unique stored event")
            stored, = matches
            dispositions = (analysis.completion or {}).get("observation_dispositions", [])
            completed = any(d["id"] == row["prediction_id"] and d.get("check_completed") for d in dispositions)
            observed = stored.verdict if completed else "unfinished"
            verification[f"{label}/{observed}"] += 1
        elif row["stage"] == "initial":
            if row["prediction_id"] not in {f.observation.id for f in analysis.observations}:
                raise ValueError("Initial claim needs a saved observation")
            initial[label] += 1
        elif row["stage"] == "report":
            report[label] += 1
        else:
            raise ValueError("Unknown claim review stage")
    queries = review["retrieval_reviews"]
    if review["retrieval_checked"] and (len(queries) != len(question_ids) or {r["id"] for r in queries} != question_ids):
        raise ValueError("Retrieval review must cover each frozen question once")
    outcomes = {"correct", "justified_abstention", "partial", "wrong", "unsupported_answer", "unscorable"}
    if any(row["outcome"] not in outcomes or not row["reason"] for row in queries):
        raise ValueError("Retrieval review needs a valid outcome and reason")
    counts = Counter(row["outcome"] for row in queries)
    scorable = len(queries) - counts["unscorable"]
    non_supporting_labels = {"contradicted", "insufficient"}
    judged_negative = sum(n for key, n in verification.items()
                          if key.split("/")[0] in non_supporting_labels and not key.endswith("/unfinished"))
    false_supported = sum(verification[f"{label}/supported"] for label in non_supporting_labels)
    return {
        "initial_claims_by_label": dict(initial),
        "verification_false_support": {"count": false_supported, "denominator": judged_negative,
                                       "rate": false_supported / judged_negative if judged_negative else None},
        "verification_reference_vs_stored": dict(verification),
        "report": {"review_complete": review["report_checked"], "claims_by_label": dict(report),
                   "omitted_reference_ids": review["report_omitted_reference_ids"]},
        "retrieval": {"review_complete": review["retrieval_checked"],
                      "counts": dict(counts), "reviewed": len(queries),
                      "correct_or_justified_abstention_rate":
                          (counts["correct"] + counts["justified_abstention"]) / scorable if scorable else None},
    }


def main():
    cases = read(HERE / "cases.json")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=cases)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, help="Saved analysis.json or a Verification handoff result")
    parser.add_argument("--review", type=Path, help="Include to score. Omit for a local review packet.")
    parser.add_argument("--validate-only", action="store_true",
                        help="Check frozen annotations and source frames without reading model outputs")
    parser.add_argument("--caviar-reference", action="store_true",
                        help="Use a locally aligned CAVIAR conversion instead of a human-reviewed reference")
    args = parser.parse_args()
    spec = cases[args.case]
    path = args.artifact or spec["artifact"]
    gold = read(args.annotations)
    if args.caviar_reference:
        eligible = gold.get("reference_kind") == "caviar_conversion" and gold.get("alignment_status") == "local_verified"
    else:
        eligible = gold["review_complete"] and bool(gold["reviewers"])
    if not eligible or gold["case"] != args.case or gold["source_sha256"] != spec["sha256"]:
        parser.error("Supply an eligible reference for this case and source hash")
    video = ingest(Path(spec["source"]))
    if video.sha256 != spec["sha256"] or video.duration_us != spec["duration_us"]:
        parser.error("Source differs from the case manifest")
    for section in ("events", "questions"):
        if len({row["id"] for row in gold[section]}) != len(gold[section]):
            parser.error(f"Duplicate IDs in {section}")
    positive_ids = {row["id"] for row in gold["events"] if row["status"] == "supported"}
    for question in gold["questions"]:
        if (question["expectation"] not in {"answer", "abstain", "unscorable"}
                or not set(question["expected_event_ids"]) <= positive_ids
                or (question["expectation"] == "answer") != bool(question["expected_event_ids"])):
            parser.error("Each question needs a reference outcome and compatible expected event IDs")
    for ref in gold["events"]:
        Interval(**ref["interval"]).validate(video.duration_us)
        if ref["status"] not in {"supported", "ambiguous"} or not ref["supporting_frames"]:
            parser.error("Each reference needs a status and supporting frames")
        for frame in ref["supporting_frames"]:
            pts = frame["pts"]
            index = frame["display_index"]
            if not (0 <= index < len(video.frame_pts) and video.frame_pts[index] == pts
                    and int(video.time_at_pts(pts) * 1_000_000) == frame["source_time_us"]):
                parser.error("A reference frame does not resolve to the source")
    if args.validate_only:
        print(json.dumps({
            "case": args.case, "source_sha256": video.sha256,
            "annotation_sha256": artifact_hash(args.annotations),
            "event_count": len(gold["events"]), "question_count": len(gold["questions"]),
            "valid": True,
        }, indent=2))
        return
    if path is None:
        parser.error("This case has no comparable saved run. Supply a saved artifact.")
    digest = artifact_hash(path)
    if args.artifact is None and digest != spec["artifact_sha256"]:
        parser.error("Saved baseline artifact differs from the case manifest")
    analysis, stats, inspections = load_run(video, path)
    predicted = predictions(analysis)
    excluded_categories = {}
    if args.caviar_reference:
        for stage, rows in predicted.items():
            excluded_categories[stage] = dict(Counter(row["category"] for row in rows if row["category"] != "person_moved"))
            predicted[stage] = [row for row in rows if row["category"] == "person_moved"]
    output = {"case": args.case, "source_sha256": video.sha256, "artifact_sha256": digest,
              "annotation_sha256": artifact_hash(args.annotations), "reference_kind": gold.get("reference_kind", "human"),
              "detection_excluded_categories": excluded_categories, "execution": stats}
    if args.review is None:
        if args.caviar_reference:
            output["temporal_candidates_for_review"] = {
                stage: {row["id"]: [ref["id"] for ref in gold["events"]
                                   if row["category"] == ref["category"]
                                   and iou(row["interval"], ref["interval"]) >= THRESHOLD]
                        for row in rows}
                for stage, rows in predicted.items()
            }
        output.update(predictions=predicted, unresolved=list(map(asdict, analysis.unresolved)), report=analysis.report,
                      retrieval=[{"id": q["id"], **asdict(analysis.ask(q["text"]))} for q in gold["questions"]])
    else:
        review = read(args.review)
        if (review["source_sha256"] != video.sha256 or review["artifact_sha256"] != digest
                or review["annotation_sha256"] != output["annotation_sha256"] or not review["reviewer"]):
            parser.error("Review must identify the frozen source, run artifact and reviewer")
        if not set(review["report_omitted_reference_ids"]) <= positive_ids:
            parser.error("Report omissions must reference supported annotations")
        output["event_scores"] = {}
        for stage, rows in predicted.items():
            exclusions = review.get("caviar_unlabelled_predictions", {}).get(stage, {}) if args.caviar_reference else {}
            if (not set(exclusions) <= {row["id"] for row in rows}
                    or any(not isinstance(reason, str) or not reason.strip() for reason in exclusions.values())
                    or set(exclusions) & review["event_links"][stage].keys()):
                parser.error("Unlabelled-region exclusions need known, unlinked prediction IDs and reasons")
            output["event_scores"][stage] = score_events(
                [row for row in rows if row["id"] not in exclusions], gold["events"], review["event_links"][stage],
            )
            if args.caviar_reference:
                output["event_scores"][stage]["unlabelled_region_exclusions"] = exclusions
        output["citation_checks"] = {stage: citation_checks(video, rows, inspections) for stage, rows in predicted.items()}
        output["citation_checks"]["unresolved"] = citation_checks(
            video, [{"citations": list(map(asdict, e.citations))} for e in analysis.unresolved], inspections,
        )
        output.update(score_reviews(review, analysis, {q["id"] for q in gold["questions"]}))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
