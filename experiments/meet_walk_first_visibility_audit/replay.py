"""Rebuild the manifest, reviewer pair and offline validator replay from the saved run."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from security_augmented.agents import AgentRun
from security_augmented.contracts import FrameEvidence, Interval, VideoError
from security_augmented.observation import FrameReference, Observation
from security_augmented.video import _decode, _run, ingest
from security_augmented.workflow import Budget, Citation, Finding

output = Path(__file__).resolve().parent
record = Path("experiments/meet_walk_evaluation.i2mvYw/run/analysis.json")
source = Path("data/raw/Meet_WalkTogether1_pts.mp4")
analysis = json.loads(record.read_text())["analysis"]
video = ingest(source)
assert video.sha256 == analysis["video"]["sha256"]
probe = json.loads(_run("ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "frame=pts", "-of", "json", str(source)).stdout)
assert tuple(int(f["pts"]) for f in probe["frames"]) == video.frame_pts
entries = [e for e in analysis["evidence"] if e["interval"]["start_us"] in (0, 8_000_000, 20_000_000)]
records = [f for e in entries for f in e["findings"]]
seed, late, associated, witness = records
trace = [d for d in analysis["trace"] if d["action"] in (
    "inspect", "tool_result", "correspondence", "verdict_rejected", "transition_evidence", "verdict",
) and (any(f["observation"]["id"] in d["observation_ids"] for f in records)
       or (d["details"] or {}).get("candidate_id") in {f["observation"]["id"] for f in records})]
indices = tuple(sorted({f["display_index"] for e in entries for f in e["inspection"]["frames"]}
                       | set(range(650, 708))))
pixels = dict(zip(indices, _decode(video, indices), strict=True))
manifest = {}
for i, rgb in pixels.items():
    pts = video.frame_pts[i]
    manifest[i] = {"index": i, "pts": pts, "source_time_us": int(video.time_at_pts(pts) * 1_000_000),
                   "rgb24_sha256": hashlib.sha256(rgb).hexdigest()}
for f in [f for e in entries for f in e["inspection"]["frames"]] + [f for r in records for f in r["citation"]["frames"]]:
    decoded = manifest[f["display_index"]]
    assert all(decoded[k] == f[k] for k in ("pts", "source_time_us", "rgb24_sha256"))

def restore(row):
    o, c = row["observation"], row["citation"]
    frames = tuple(FrameEvidence(**f) for f in c["frames"])
    obs = Observation(o["id"], o["inspection_id"], o["category"], o["description"],
                      FrameReference(tuple(o["evidence"]["frame_ids"])), o["visibility_limits"], o["uncertainty"])
    return Finding(obs, Citation(c["video_id"], c["inspection_id"], c["modality"], Interval(**c["interval"]), frames))

first, target = map(restore, (seed, witness))
first_id, target_id = first.observation.id, target.observation.id
assessment = next(d["details"]["assessments"] for d in trace
                  if d["action"] == "correspondence" and target_id in d["observation_ids"])
before, after = target.citation.frames
decision = {"action": "verdict", "verdict": "supported", "ids": [first_id, target_id],
            "reason": "Reconstructed first-visibility claim.", "correspondence": assessment,
            "transition": {"observation_id": first_id, "before_frame_id": before.id, "after_frame_id": after.id}}
replays = []
for ref in (first_id, target_id):
    action = {**decision, "transition": {**decision["transition"], "observation_id": ref}}
    agent = AgentRun(SimpleNamespace(duration_us=video.duration_us), None, None, Budget(**analysis["budget"]), [])
    try:
        result = agent.verdict(first, action, {first_id: first, target_id: target})
    except VideoError as exc:
        replays.append({"input": action, "error": str(exc)})
    else:
        replays.append({"input": action, "verdict": result[1], "source_interval_us": vars(result[3])})
assert replays[0]["error"] == "Transition frames are outside the cited observation"
assert replays[1]["verdict"] == "supported"

pair_dir = output / "blinded_pair"
pair_dir.mkdir(exist_ok=True)
for name, idx in (("before", 675), ("after", 700)):
    image = _run("ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
                 "-video_size", f"{video.width}x{video.height}", "-i", "pipe:0",
                 "-frames:v", "1", "-threads", "1", "-c:v", "png", "-f", "image2pipe", "pipe:1",
                 input_bytes=pixels[idx]).stdout
    (pair_dir / f"{name}.png").write_bytes(image)
(output / "evidence-manifest.json").write_text(json.dumps({
    "source": str(source), "source_sha256": video.sha256, "time_base": str(video.time_base),
    "record": str(record), "decoded_frames": list(manifest.values()),
    "recorded_observations": records,
    "recorded_inspections": [{"phase": e["phase"], "inspection": e["inspection"]} for e in entries],
    "recorded_trace": trace, "reconstructed_replays": replays,
}, indent=2) + "\n")
print("Verified source PTS and decoded frame hashes. Replays: rejected with seed; supported with target.")
