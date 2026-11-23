# Temporal hypothesis evaluation

## Recorded baseline

The source is `data/raw/Meet_WalkSplit_pts.mp4`, with 624 presentation frames at 25 fps and a 1/12800 time base. The [recorded run](../meet_walk_split_500ms.bqVoWC/run/analysis.json) sampled at 500 ms in three windows. The replay checks source identity, PTS and decoded RGB24 hashes against all recorded inspection frames.

Investigation accounted for all five observations. It delegated three, associated a single-frame appearance with the early movement, and excluded a static-object observation. Verification's sole targeted request was frames [0,2) s, which returned early movement observations. It accepted movement at 0–0.52 s, rejected the object's appearance claim, and accepted movement at 10–14.52 s directly from its initial citation. Reporting selected the earliest movement. The live run completed all three verification checks, with one associated observation still unresolved. No recorded decision proposed a trajectory split, and no targeted request addressed the end of the later movement. The initial windows already sampled later times; the retained observation for the middle window cited only frames 250–363 through 14.52 s. There were six recorded reasoning calls, with 12,804 total reported reasoning tokens.

## Paired controller replay

The manifest preserves the normalized live trace and its recorded media outputs. The scripted baseline reconstructs actions from that trace, including the exact accepted frame pairs, and reproduces the recorded timeline and call count. The original raw decision payloads are unavailable. This is a reconstruction, not a second live baseline.

The temporal script retains all initial observations, candidates and verdicts. Its only operational comparison is one added frame request [14.52,19.52) s at the later verification. The scripted hypothesis is that the two figures might maintain a jointly visible direction, visibly diverge, or become separately untrackable. The distinguishing evidence would be two traceable trajectories on both sides of the last cited anchor. The request starts at the existing 14.52 s anchor, overlaps the delegated span, and uses the same 500 ms sampler. Both variants have identical limits: 14 logical role calls, four inspections, four candidates and four verification decisions per candidate. B spends an additional available call and slot; this is a matched-cap comparison.

| Variant | Hypothesis and inspection | Evidence obtained or missing | Conclusion justified | Cost |
|---|---|---|---|---|
| A, recorded; scripted replay agrees | Verify the reported movement. Targeted [0,2) s only. | Recorded targeted results concern the early figure. Later citation ends at 14.52 s. | Movement up to the cited endpoint. Continuation and separation were not evaluated. | Six reasoning decisions, one inspection. |
| B, scripted | Inspect [14.52,19.52) s to look for continuation, divergence, or loss of trackability. | Local samples: anchor frame 363 (14.52 s), followed by 376, 388, 401, 413, 426, 438, 451, 463 and 476 (15.04–19.04 s). All nine later frames are novel to the seed. No recorded provider answer exists for this request; the replay returns missing coverage from the targeted-response archive. | The same supported movement interval remains. No model conclusion about its aftermath was observed or simulated. | Seven scripted role decisions and two lookup attempts, no additional inference. Live latency and usage are unknown. |

## Source review and inference limit

A provisional local review shows two figures moving toward the left around 10–12 s. Near the end of the cited stretch the bright foreground, rail and partial occlusion make following both trajectories less reliable. The proposed samples cover the relevant change in visibility by extending beyond frame 363. They are more relevant to this specific question than a lookup at 0–2 s, but they do not clearly separate joint continuation from physical divergence. Failure to keep both figures in view supports uncertainty about their subsequent paths. It does not establish a split or departure. Independent reviewers were unavailable. The local review sequence and neutral rubric are prepared; agreement is unmeasured.

**No model performance improvement is established.** B was human-scripted and used one extra lookup within the same caps. This tests feasibility of obtaining relevant frames and the workflow's handling of a missing archived response. It does not isolate the effect of explicit hypotheses from spending another inspection. A paired assessment would need independent annotations on this passage, actual agent-chosen requests under matched inspection opportunities, and recorded perception responses to those requests. Compare against a control also permitted a follow-up inspection, then score whether each response and its citations justify the resulting conclusion or abstention. No fourth agent or production changes were evaluated.

## Reproduce

From the repository root:

```sh
ffprobe -v error -select_streams v:0 -show_entries stream=time_base,nb_frames,r_frame_rate -of json data/raw/Meet_WalkSplit_pts.mp4
.venv/bin/python experiments/temporal_hypothesis_evaluation/replay.py
```

The replay verifies the source and recorded hashes, reproduces the baseline timeline, and asserts that B's extra lookup has no archived response. It creates the JSON evidence manifest and local reviewer sequence. No live Gemini calls or external transfers were made.
