"""Offline replay and frame manifest. Run from the repository root."""
import hashlib
import json
from pathlib import Path

from security_augmented.contracts import FrameEvidence, Interval
from security_augmented.observation import FrameReference, Observation
from security_augmented.video import _decode, _run, ingest, sample
from security_augmented.workflow import ArchivedInspection, Budget, Citation, Finding, _analyze

out = Path(__file__).resolve().parent
record = Path("experiments/meet_walk_split_500ms.bqVoWC/run/analysis.json")
r = json.loads(record.read_text())
a = r["analysis"]
video = ingest(Path("data/raw/Meet_WalkSplit_pts.mp4"))
assert video.sha256 == a["video"]["sha256"]

def restore(entry):
    findings = []
    for row in entry["findings"]:
        o, c = row["observation"], row["citation"]
        obs = Observation(o["id"], o["inspection_id"], o["category"], o["description"],
                          FrameReference(tuple(o["evidence"]["frame_ids"])), o["visibility_limits"], o["uncertainty"])
        frames = tuple(FrameEvidence(**f) for f in c["frames"])
        findings.append(Finding(obs, Citation(c["video_id"], c["inspection_id"], c["modality"],
                                              Interval(**c["interval"]), frames)))
    return ArchivedInspection("recorded", entry["modality"], Interval(**entry["interval"]), entry["status"],
                              tuple(findings), coverage=tuple(Interval(**s) for s in entry["coverage"]))

initial = [restore(e) for e in a["evidence"] if e["phase"] == "initial"]
targeted = [restore(e) for e in a["evidence"] if e["phase"] == "targeted"]
trace = a["trace"]
triage = next(row["details"]["dispositions"] for row in trace if row["action"] == "triage")
ids = [row["id"] for row in triage if row["status"] == "delegated"]
dispositions = [row for row in triage if row["status"] != "delegated"]
focus = a["timeline"][1]["observation_ids"][0]
pairs = {row["details"]["observation_id"]: row["details"] for row in trace if row["action"] == "transition_evidence"}
verdicts = {row["details"]["candidate_id"]: row for row in trace if row["action"] == "verdict"}
proposal = Interval(14_520_000, 19_520_000)
step = a["coverage"]["plan"]["frame_step_us"]
alternative = sample(video, proposal, list(range(proposal.start_us, proposal.end_us, step)))

def replay(temporal):
    calls, inspections = [], []
    observed_inspects = set()

    def tool(span, modality):
        inspections.append({"modality": modality, "interval": vars(span)})
        return [e for e in targeted if e.interval == span and e.modality == modality]

    def decide(role, context):
        calls.append(role)
        if role == "investigation":
            return {"action": "delegate", "ids": ids, "dispositions": dispositions, "reason": "Recorded triage."}
        if role == "reporting":
            return {"action": "report", "lead_id": ids[0], "emphasis": "evidence", "reason": "Recorded report choice."}
        seed = context["candidate_id"]
        if seed not in observed_inspects and (seed == ids[0] or (temporal and seed == focus)):
            observed_inspects.add(seed)
            span = Interval(0, 2_000_000) if seed == ids[0] else proposal
            return {"action": "inspect", "modality": "frames", **vars(span), "reason": "Scripted inspection."}
        row = verdicts[seed]
        result = {"action": "verdict", "verdict": row["details"]["outcome"],
                  "ids": row["observation_ids"], "correspondence": [], "reason": row["reason"]}
        if seed in pairs:
            result["transition"] = {key: pairs[seed][key] for key in ("observation_id", "before_frame_id", "after_frame_id")}
        return result

    result = _analyze(video, initial, tool, Budget(**a["budget"]), decide=decide,
                      controller="langgraph", initial_scan="completed")
    actual = [(e.category, vars(e.interval)) for e in result.timeline]
    assert actual == [(e["category"], e["interval"]) for e in a["timeline"]]
    return {"calls": calls, "inspections": inspections, "completed_checks": result.completion["completed_checks"],
            "timeline": actual, "tool_results": [d.details for d in result.trace if d.action == "tool_result"]}

baseline, temporal = replay(False), replay(True)
assert len(baseline["calls"]) == len(r["role_calls"]) == 6
assert len(temporal["calls"]) == 7 and temporal["tool_results"][-1]["status"] == "missing"

frame_records = [f for e in a["evidence"] for f in e["inspection"]["frames"]]
all_ids = tuple(sorted({f["display_index"] for f in frame_records}
                       | {f.display_index for f in alternative.frames} | set(range(250, 501))))
pixels = dict(zip(all_ids, _decode(video, all_ids), strict=True))
manifest = {i: {"index": i, "pts": video.frame_pts[i],
                "source_time_us": int(video.time_at_pts(video.frame_pts[i]) * 1_000_000),
                "rgb24_sha256": hashlib.sha256(rgb).hexdigest()} for i, rgb in pixels.items()}
for f in frame_records:
    assert all(manifest[f["display_index"]][k] == f[k] for k in ("pts", "source_time_us", "rgb24_sha256"))
(out / "evidence-manifest.json").write_text(json.dumps({
    "record": str(record), "source_sha256": video.sha256, "time_base": str(video.time_base), "budget": a["budget"],
    "recorded_evidence": a["evidence"], "recorded_trace": trace, "recorded_role_calls": r["role_calls"],
    "decoded_frames": list(manifest.values()), "scripted_baseline": baseline, "scripted_temporal": temporal,
    "alternative_local_frames": [manifest[f.display_index] for f in alternative.frames],
    "alternative_provider_output": None,
}, indent=2) + "\n")
# Generated locally for blinded review, without model labels or conclusions.
_run("ffmpeg", "-v", "error", "-y", "-ss", "10", "-i", video.source_path, "-t", "10", "-map", "0:v:0",
     "-c:v", "ffv1", str(out / "review-sequence.mkv"))
print("Verified source, recorded hashes, and paired replays. B's extra lookup: missing archived response.")
print([(f.display_index, f.source_time_us) for f in alternative.frames])
