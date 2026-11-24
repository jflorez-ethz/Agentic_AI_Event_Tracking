# Operator review queue

## Rule and source

The group plan *Security, Augmented: project concept and work plan* (PDF, p. 8, section Guardrails) states:

- "Missing context produces unknown and a question to the operator."
- "Person-down and fire events are never dismissed by the agent."

The system therefore aims to let a human decide quickly rather than to decide everything alone. Per ADR-001, the taxonomy, including which categories are never dismissed, still needs supervisor confirmation before held-out evaluation.

## Behaviour

Implemented in `src/security_augmented/review.py` for the model-guided workflow. The deterministic baseline is unchanged.

- The strict `supported` verdict is unchanged. Event verdicts are not rewritten.
- A security-relevant event (every event category except `person_moved` and `person_appeared`) that does not reach `supported` becomes a `needs_review` alert, with two exceptions:
  - `person_enters_area` is never an alert while no monitored zone is configured (see below).
  - An event contradicted by verification (`unsupported`) is an alert only for categories that are never dismissed (`person_fell`). Others are listed as "écartés par la vérification".
- Routine person activity (`person_moved`, `person_appeared`) is never an alert.
- An alert is never evidence. Retrieval answers, event-relative anchors and the report lead use supported events only.

Each alert records a deterministic reason code derived from the run trace:

| Code | Meaning |
|---|---|
| `not_checked` | Deferred, excluded or omitted during triage |
| `missing_corroboration` | Checked, but the inspected images did not corroborate it (including a verifier's own `insufficient`) |
| `inspection_rejected/<code>` | The final step was a pre-dispatch inspection rejection, e.g. `no_new_frames` |
| `invalid_verdict` | The verification decision was rejected |
| `unfinished` | Iteration or call limit, failed inspection, or no verdict |
| `contradicted` | Verification judged the images do not show it (alert only if never dismissed) |

The report starts with **Alertes à vérifier**. Each alert gives:

- what happened;
- when, in source time;
- a short frame selection: first and last cited frame plus the frames the perception description names (F-labels), at most six;
- why it is not confirmed (the code in plain language, then the recorded reason, flagged when the model text reads as affirmative);
- one question for the operator.

A **Non retenus comme alertes** list follows, then the confirmed findings.

`analysis.json` stores `analysis.review` with `alerts` (stable `id`, category, code, frames, empty `operator_label`), `not_alerted` and `counts` (`needs_review`, `supported_security`, `not_alerted`). The CLI also writes `alerts.csv`, a blank labelling sheet with what, when and which frames, but no model verdict or reasons. Reviewers fill it in without seeing the model's judgement. Precision can then be measured.

## Unclear observations that suspect a security event

The CLI asks Perception for `possible_category` on every observation. An `insufficient_evidence` observation names the event it suspects but could not confirm, or `none`; every other observation must use `none`. The field is opt-in (`ObservationRequest.possible_category`), so archived replays send byte-identical requests.

An unclear observation whose `possible_category` is a security category becomes a `needs_review` alert with reason code `unclear_observation`, marked "possible". `person_enters_area` is excluded while zones are absent. No alert is raised when a supported event or an existing alert of the same category overlaps it within ±2 s in the same video. `analysis.review.counts.unclear` records how many there are.

Simulation on the eight archived unclear observations, with the category a reader would expect Perception to suspect (the real field still needs live runs):

| Simulated alert | Truth (XML) |
|---|---|
| LeftBag_AtChair 35.0–37.0 s, object_removed | True (pickup at 37.20 s); the only signal from either Gemini or the stationary-object detector |
| Fall clip 11.5–13.0 s, person_fell | False (the fall is at 26.4 s) |

Three other cases were duplicates of an existing alert or supported event and were dropped. Three suspected no specific event.

## Entry alerts and monitored zones

`person_enters_area` alerts return once monitored zones are configured (detector C1 of the plan). Without a defined zone or boundary, an entry claim cannot be confirmed. Every such observation would remain an alert. In the step-0 simulation over the archived runs, they were 8 of 11 alerts, all ordinary passages at the image edge or out of a corridor, with two duplicates. They are listed as "zone non définie" until then.

## Simulation on archived runs (2026-11-24)

| Outcome | Runs | Truth |
|---|---|---|
| 2 alerts: box placement, `not_checked` (`leftbox_live.qyrM8F`) and `inspection_rejected/no_new_frames` (`leftbox_live.1iXjTj`) | LeftBox | Both true (CAVIAR XML: box object from frame 571, 23.08 s PTS) |
| 8 `zone_undefined` | Meet_WalkTogether1 | Real passages, no zone defined |
| 1 `contradicted` `object_appeared` | Meet_WalkSplit | False: a fixed case visible from the first frame |
| Box and fall confirmed (`supported`) | `leftbox_live.HwKyEx`, `fall_live.spFaYl` | True |

## Known gaps (not implemented)

- An `insufficient_evidence` observation that mentions a possible fall is not a security category, so it is never an alert. Example: the 11.5 s crouch in `fall_live.spFaYl`.
- Video after the initial scan (30 s maximum) is uninspected. The person in `Rest_FallOnFloor` gets up at 38.24 s. Uninspected time is not yet presented to the operator as an unknown.
- Direct visual verdicts sometimes return `insufficient` or `unsupported` with an affirmative reason. The report flags this heuristically. The root cause is to be diagnosed from the archived role decisions.
- Fire events have no category yet.
