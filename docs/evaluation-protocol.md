# Evaluation protocol

Status: proposed, not executed. Freeze category definitions, split, matching rules and supervisor-agreed acceptance thresholds before the held-out evaluation. All examples below are provisional until checked against the available footage.

## Scope and taxonomy

Use prerecorded, single-camera scenes and observable visual actions. Initial candidate categories:

| Category | Positive criterion | Boundary / exclusion |
|---|---|---|
| `person_enters_area` | A person visibly crosses a defined area boundary into view. | Do not infer authorization, identity or intent; entry outside the field of view is unknown. |
| `object_placed` | A visible object is put onto a visible surface and remains there. | A partial view that does not establish the action is ambiguous; do not infer ownership. |
| `object_removed` | A visible object is picked up and visibly leaves its prior location. | Do not label theft or infer the identity or destination of the person/object. |

Definitions, region boundaries and which categories are included must be agreed after inspecting available footage. Annotate `uncertain/occluded` visibility separately from event categories; do not force an event or negative label where the footage cannot establish one. Candidate alerts include true, contradictory and unresolvable claims.

## Data, annotation and split

Use footage with documented permission and approved provider transfer. Two annotators independently view the original recordings and label event category, start/end intervals with boundary uncertainty, visible/occluded spans, event descriptions, and ambiguous or off-camera periods. Independently author questions, relevant source intervals and candidate claims with `supported`, `contradicted`, or `insufficient` labels. Annotators must not see system outputs while creating ground truth. Adjudicate disagreements, record original labels and adjudication, and report agreement with counts and an appropriate agreement statistic where data permit.

Split by recording or camera/scene, never adjacent windows from the same recording across development and held-out sets. Include negative and paraphrased queries, brief events shorter than the sampling gap, window-boundary events, lookalikes, occlusion, visibility gaps, out-of-view actions, contradictory alerts and no-answer cases where the footage permits. Document the number of recordings, duration, events per class, queries and availability of each case; small samples limit conclusions. No dataset size or success threshold is asserted until resources are known.

## Matching and metrics

Predefine a one-to-one matching rule between predicted and annotated events: same category and temporal intersection-over-union (IoU) at a threshold fixed on development data; resolve competing matches deterministically by greatest IoU. If true boundaries are uncertain, preserve uncertainty and report a sensitivity analysis rather than present a falsely exact score. Count unmatched predictions and references as false positives and false negatives. Report counts and denominators alongside every rate.

| Target | Metrics and caveats |
|---|---|
| Timestamped observations | Per-class precision and recall; IoU and absolute start/end error for matched events; missed-event count; stratify by duration and visibility. For frame-only observations, evaluate frame-supported content separately from event interval localization. |
| Timeline | Event precision/recall and duplicate or unsupported merge counts; pairwise ordering accuracy only for matched reference events whose ordering is unambiguous; count invented temporal or causal links separately. |
| Retrieval | Query-level Recall@k: fraction of queries with at least one reference interval overlapping a returned interval under a predeclared criterion; also event-level recall, interval IoU and no-answer behavior. Measure against all annotated events, including those not described by the model. |
| Report | Independently judge each atomic factual claim against its cited original footage: supported, contradicted or indeterminate. Report supported-claim fraction, unsupported claims, omissions, citation resolution rate and relevant interval correctness. A resolving link is not semantic support. |
| Verification | Three-way confusion matrix, per-class recall, insufficient-evidence recall, and false-supported rate among reference contradicted/insufficient cases. Record cases where additional inspection was requested and whether it was useful. |
| Coordination | Paired comparison of multi-agent and simpler baseline on the same cases, reporting the above outcomes, tool/model calls, elapsed time and observed cost. |

Report per-recording and per-category cases, and bootstrap uncertainty by recording where enough independent recordings exist. Do not infer generalizable accuracy from one pilot video. Include failure cases and the number of excluded or unavailable examples.

## Baselines and error attribution

Compare against a fixed sequential single-model pipeline with the same inputs, model family, observation corpus, retrieval access, task set and maximum inspection/model-call budget. Both approaches may use fewer than the maximum; report actual use. The baseline can use a simple prompt and deterministic pipeline, but must not receive the specialized multi-agent handoffs. Differences combine coordination and prompt/workflow effects, so do not claim a causal mechanism without further ablations.

Use oracle interventions, clearly labeled as diagnostic rather than deployable scores:

1. Run the same retrieval questions against human-authored observations to estimate retrieval loss separately from perception loss; language differences still confound the comparison.
2. Give the verifier the gold relevant intervals to assess reasoning and verification without retrieval failure.
3. Give the reporter gold verified claims to assess report generation separately.

Assign each error its earliest supported source—perception, retrieval, reasoning/verification, reporting, or timestamp/provenance—with multiple contributing causes recorded. Review cited source footage rather than judging model captions alone. Compare lexical search and candidate embeddings using the same corpus, questions, relevant-interval labels and compute/usage logs.

## Execution and reproducibility

Version manifests, annotations, taxonomy, split, matching settings, source hashes, software/model IDs, prompts, sampling parameters and API settings. Save actual frame PTS, inspection inputs, raw model responses, failed calls, evidence IDs, decisions and stop reasons. Use fixed seeds where the tool supports them, rerun selected cases and report variability; provider models may remain nondeterministic or change. Protect source footage according to dataset permissions.

Before scoring, validate timestamps and evidence links through replay. A claim with a broken citation is an integrity failure regardless of apparent plausibility. Distinguish not retrieved from disproved, and treat occluded or absent footage as insufficient rather than a negative claim. E1's single-recording checks and blocked conditions are specified in the [implementation plan](implementation-plan.md).
