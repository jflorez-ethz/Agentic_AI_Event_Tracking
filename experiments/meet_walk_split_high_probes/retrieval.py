"""Evaluate local retrieval on the saved Verification result without running agents."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from probe import CONTINUATION_RECORD, SOURCE, restore
from security_augmented.contracts import FrameEvidence, Interval, VideoError
from security_augmented.video import ingest
from security_augmented.workflow import Analysis, Budget, Citation, Event, RelationalFinding

RESULT = Path(__file__).with_name("verification.Uk6X57") / "run" / "result.json"
QUESTIONS = (
    "What happened after the two people approached each other?",
    "What happened before the person entered the atrium?",
    "What happened between 10 and 15 seconds?",
    "Did the two people separate afterward?",
    "What happened after an event that never occurred?",
)


def load_analysis(result_path=None):
    archived = json.loads(CONTINUATION_RECORD.read_text())["analysis"]
    result = json.loads((result_path or RESULT).read_text())
    video = ingest(SOURCE)
    if video.sha256 != result["source_sha256"] or video.sha256 != archived["video"]["sha256"]:
        raise VideoError("Source differs from the archived run")
    def citations(rows):
        return tuple(Citation(c["video_id"], c["inspection_id"], c["modality"], Interval(**c["interval"]),
                              tuple(FrameEvidence(**frame) for frame in c["frames"])) for c in rows)

    def event(row):
        relation = row.get("relation")
        if relation:
            relation = RelationalFinding(**(relation | {
                "interval": Interval(**relation["interval"]),
                "citations": citations(relation["citations"]),
            }))
        return Event(row["category"], Interval(**row["interval"]), row["verdict"], row["reason"],
                     tuple(row["observation_ids"]), citations(row["citations"]), relation)

    events = tuple(event(row) for row in result["events"])
    return Analysis(
        video, (), restore(archived), tuple(e for e in events if e.verdict == "supported"),
        tuple(e for e in events if e.verdict != "supported"), (), "", Budget(**result["budget"]),
        result["completion"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, help="Saved Verification result to query")
    parser.add_argument("--question", action="append", help="Local question. Defaults to the five evaluation queries.")
    args = parser.parse_args()
    analysis = load_analysis(args.result)
    print(json.dumps([{"question": q, **asdict(analysis.ask(q))} for q in args.question or QUESTIONS], indent=2))


if __name__ == "__main__":
    main()
