# Adaptive Verification inspection pilot

The pilot runs the existing Investigation, Verification and Reporting roles through LangGraph with scripted decisions and an offline review callback. It reuses the targeted frame tool for extraction, coverage, response validation and citation handoff. The preflight adapter has no client. It validates RGB24 against the inspection and checks the existing serialized inline payload estimate before dispatching to the local callback.

A Verification inspection decision can include `sampling_step_ms` (500 by default, or 250), integer `start_us` and `end_us` defining a half-open source interval, `reason` identifying the uncertainty, and a concrete `question`. For example:

```json
{
  "action": "inspect",
  "modality": "frames",
  "start_us": 6000000,
  "end_us": 8000000,
  "sampling_step_ms": 250,
  "reason": "The coarse views leave the onset of silhouette overlap uncertain.",
  "question": "Between which views do the two silhouettes first overlap?"
}
```

The runner exposes available steps and remaining media slots to Verification. The tool requires overlap with the candidate citation and execution headroom for a follow-up decision. It preselects canonical source indices and rejects a request if every selected frame is already in the initial inspection, successful prior inspections or visible citations. The fine rate allows one charged inspection per candidate and at most five seconds and 20 unique frames. The existing global tool count, role/iteration budgets, failure handling and verdict validation still govern the run. The targeted media allowance cannot exceed the inspection allowance. A payload failure consumes the tool slot and leaves the media slot untouched. The simulated media counter measures dispatches to the offline review callback. It is not a measure of physical HTTP traffic.

## Comparison on archived WalkSplit evidence

| Outcome | 500 ms | 250 ms | Effect |
|---|---|---|---|
| Apparent convergence and proximity | Shared frames 150 and 163 show decreasing projected spacing; frame 163 shows the nearby figures | Retains these frames and adds intermediate views | Same local verdict, no demonstrated semantic improvement |
| Overlap onset | Last distinct silhouettes at 6.52 s, overlap visible at 7.00 s | Overlap visible by 6.76 s | Observed onset bracket narrows from 480 ms to 240 ms |
| Local divergence | Shared frames 250 and 325 support increased projected spacing with distinguishable paths | Adds intermediate views of the paths near the seating/corridor boundary | Better temporal sampling, same local verdict |
| Same-pair correspondence | Insufficient evidence across the overlap and between windows | Extra views still leave overlap and no reviewed link chain | Same insufficient verdict |

The [source manifest](adaptive-frame-manifest.json) records frame IDs, integer PTS, actual source timestamps and RGB24 digests. The [source assessment](adaptive-sampling.md) explains the single-reviewer marks and the separate synthetic continuity control. The onset bracket is based on observations at sampled instants and does not establish the first instant of overlap. A valid citation or narrower timing bracket supplies no new identity judgment.

## Offline check

From the repository root:

```sh
.venv/bin/python -m pytest -q experiments/relational_motion
```

The pilot tests exercise real FFmpeg extraction, evidence handoff, an explicit fine request and coarse requests, no request when an inspection is unnecessary, shifted duplicates, the one-fine limit, the five-second/20-frame boundary, payload rejection, and exhausted tool, media, decision and iteration budgets. The WalkSplit relation judgments bypass the scripted observations and use the existing experiment validator with source-backed review inputs.

Keep production at 500 ms. The pilot supports a limited case for finer sampling when an interval is too wide for a specific timing question. Before integrating it into production, establish how often Verification can recognize such cases and whether independently reviewed timing gains justify the added media. The tested decisions were scripted, so the experiment does not measure how often a model would request useful evidence.
