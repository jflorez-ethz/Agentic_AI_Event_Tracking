# WalkSplit end-to-end execution audit

The initial scan succeeded on all three windows. The run recorded one supported movement, one completed unsupported verdict, two incomplete movement checks and one deferred observation. The report correctly called the investigation partial. Its three identical explanations for insufficient findings obscure three distinct execution outcomes. [Original analysis](run/analysis.json) · [Original report](run/report.md)

## What ran

| Stage and source time | Recorded action and outcome |
|---|---|
| Perception, 0–10 s | Sent 20 frames. Returned three observations about movement toward the lower-right edge, movement from the left toward the upper lobby, and first visibility followed by movement from the lower right. |
| Perception, 10–20 s | Sent 20 frames. Returned two observations of movement, one toward the upper-left hall and one toward reception. Their citation intervals extend to 15.00 and 19.52 s respectively. |
| Perception, 20–24.96 s | Sent 10 frames through 24.52 s. Successful inference with an empty validated observation list. The last interval received visual input. |
| Investigation | All five observations fit in the initial context. One delegate decision, zero searches, zero associations. The four slots went to three movement checks and one appearance check. The recorded disposition explicitly defers the reception movement because the queue is full. No independent relational task was assigned. |
| Verification 1, 0–1 s, ID prefix 762e59 | Accepted supported movement with ordered transition frames at 0 and 1 s. |
| Verification 2, 0–9.52 s, 6f06c8 | Accepted an unsupported verdict. Its model rationale says the movement “is established” and names source frames. The structured verdict and prose disagree. The trace contains no transition-validation rejection for this candidate. |
| Verification 3, 3–9.52 s, 88193f | HTTP 200, one candidate, STOP. The role response passed JSON decoding. AgentRun.action recorded “Malformed decision or unavailable action.” at decision_schema_validation. The graph finalized this check as incomplete before verdict evidence validation. The archive omits the returned fields and full response. |
| Verification 4, 10–15 s, 8ac6dd | Queued. The max_failures limit of one had already been reached. No fourth Verification model call occurred. |
| Reception movement, 10–19.52 s, acb56c | Deferred at triage, never delegated. Its unresolved Event was generated at finalization. |
| Reporting | The same failure limit prevented the Reporting model call. The deterministic renderer ran and wrote the partial report. Neither a targeted inspection nor a recovery decision executed. |

Three Perception, one Investigation and three Verification requests received HTTP 200. The four role calls each recorded one STOP candidate. The archive records per-window usage and successful observation validation for Perception. Across all seven calls the recorded input, candidate and thinking counts sum to 71,574, 1,668 and 23,941 tokens respectively. Summed model-call latency was 133.094 s. There were zero retries. The archive does not include full wire requests or raw text for the rejected role response.

## Comparison on the same source

The three inspection records match the earlier run exactly, including source ID, indices, PTS, timestamps, RGB24 hashes, requested times and frame order. Both runs recorded the same perception model, thinking level, token ceiling, adapter and prompt version. The earlier run emitted 6/4/1 observations. It separated appearance from movement in the opening window, described later walkway observations in the middle window and described a walkway traversal in the final window. The new run emitted 3/2/0. The difference first appears in Perception's returned observations. The archive gives no causal explanation for that variation. Earlier model output has no independent ground-truth status. The earlier final traversal was itself disputed. [Earlier scan](../meet_walk_split_high.uGljGL/run/analysis.json)

## Source check

The local frame sheet uses presentation-order indices 0, 13, 25, 88, 150, 163, 175, 250, 275, 300 and 325. Each decoded RGB24 digest and PTS was checked against this run's initial inspection before composing the sheet. The sheet is a JPEG viewing copy. Canonical IDs and hashes are in the archive. [Frame sheet](source-review.jpg)

- The accepted pair is `frame-d90d4107bd8820496436193b769fb8ced22c37eea0ed200d1e508f35cf4b5ae4` and `frame-c2fc7db1550a84279bf80ac6a925eee872c93aa6de233d48607e3adbe03bb1e2`. Index 13 supplies the intermediate view. A figure moves down and somewhat right toward the bottom edge, where only part remains visible. These pixels support the narrow movement verdict.
- At 3.52, 6.00, 6.52 and 7.00 s the projected gap narrows and the silhouettes begin to overlap. At 10–13 s two silhouettes follow distinguishable local paths near the seating area. Continuous identity, social joining and subsequent separation of the same pair remain unestablished. This is a local visual assessment, without independent adjudication.
- Both time ranges had sampled source evidence and overlapping textual leads. Investigation committed all slots to individual checks. No relational inspection executed, so the live relation validator had no proposal to evaluate. This run gives no measurement of the value of finer sampling.

## Corrections and evidence limits

1. Preserve distinct closure reasons in new reports. A failed decision, an exhausted budget and a deferral each have their own trace and reason. The former generic before/after sentence incorrectly suggested that all three had gone through transition validation.
2. For future rejected action shapes, retain the candidate, returned action, action availability, missing/unexpected field names and whether the reason was valid. The failing field in this archived decision is unrecoverable. The one accepted support decision supplied the required transition. The archive gives no grounds for weakening that requirement or blaming it for three failures.
3. Keep the failure and candidate budgets intact. The conflict between the second verdict and its rationale deserves review as a model-output inconsistency. Its prose alone cannot promote it to supported. Adaptive inspection adds an option at the existing tool boundary. It cannot recover a candidate already deferred or a task never assigned.
