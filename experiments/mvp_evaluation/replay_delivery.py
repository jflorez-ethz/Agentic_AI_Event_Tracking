"""Replay recorded WalkSplit outputs through the video-first LangGraph workflow, offline."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from pydantic import TypeAdapter

from security_augmented.observation import InferenceMetadata, Observation, ObservationResult
from security_augmented.workflow import Budget, InspectionPlan, analyze_video

ROLE_RECORD = Path("experiments/meet_walk_split_high_probes/independent-relational-tasks-retry-live/result.json")
SOURCE = Path("data/raw/Meet_WalkSplit_pts.mp4")


def replay(output):
    recorded = json.loads(ROLE_RECORD.read_text())
    scan = json.loads(Path(recorded["archived_scan"]).read_text())["analysis"]
    media = iter([*scan["evidence"], *recorded["targeted_evidence"]])
    decisions = iter(recorded["decisions"])
    counts = []

    class RecordedPerception:
        def infer(self, request):
            row = next(media)
            # This compares the actual source decode with every archived frame,
            # including IDs, pixel hashes and PTS, before releasing the observations.
            if json.loads(json.dumps(asdict(request.media.inspection))) != row["inspection"]:
                raise AssertionError("Source inspection differs from the archive")
            counts.append(len(request.media.inspection.frames))
            return ObservationResult(
                TypeAdapter(InferenceMetadata).validate_python(row["inference"]),
                tuple(TypeAdapter(Observation).validate_python(f["observation"]) for f in row["findings"]),
            )

    def decide(role, context):
        row = next(decisions)
        if row["role"] != role or json.loads(json.dumps(context)) != row["context"]:
            raise AssertionError(f"{role} context differs from the recorded decision")
        return row["decision"]

    result = analyze_video(SOURCE, RecordedPerception(), budget=Budget(**recorded["budget"]),
                           plan=InspectionPlan(**recorded["plan"]), decide=decide, controller="langgraph",
                           adaptive_sampling=False)
    if next(media, None) or next(decisions, None) or result.video.sha256 != recorded["source_sha256"]:
        raise AssertionError("Replay did not consume the complete source record")
    if json.loads(json.dumps(result.completion)) != recorded["completion"]:
        raise AssertionError("Replayed completion differs from archive")
    events = sorted((*result.timeline, *result.unresolved), key=lambda e: (e.interval.start_us, e.observation_ids))
    expected = sorted(recorded["events"], key=lambda e: (e["interval"]["start_us"], e["observation_ids"]))
    if json.loads(json.dumps([asdict(e) for e in events])) != expected:
        raise AssertionError("Replayed events differ from archive")

    output.mkdir(mode=0o700)
    questions = ["What happened between 10 and 15 seconds?", "Did the two people separate afterward?"]
    payload = {
        "replay": {"decision_archive": str(ROLE_RECORD), "scan_archive": recorded["archived_scan"],
                   "physical_requests": 0, "matched_frame_counts": counts,
                   "role_calls_replayed": len(recorded["decisions"]),
                   "media_input": "Local source pixels, archived normalized perception outputs",
                   "role_input": "Archived parsed Gemini decisions, matched against regenerated role contexts"},
        "analysis": asdict(result), "answers": [{"question": q, **asdict(result.ask(q))} for q in questions],
    }
    (output / "analysis.json").write_text(json.dumps(payload, indent=2) + "\n")
    (output / "report.md").write_text(result.report)
    print(json.dumps(payload["replay"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    replay(parser.parse_args().output)
