# Three-video MVP evaluation
 
See the [CAVIAR reference conversion and preliminary offline comparison](CAVIAR.md).

This is a descriptive course-project evaluation using local CAVIAR footage. All three recordings have already informed development. Treat the set as a retrospective evaluation and preserve failures. Human reference labels have **not** been collected.

## Case selection and inventory

| Case | Source reviewed | Visual conditions | Saved material |
|---|---|---|---|
| `walk_split` | Meet_WalkSplit_pts.mp4, 24.96 s | Close pedestrian movement, overlap and glare | 11 initial observations in the [scan](../meet_walk_split_high.uGljGL/run/analysis.json) and the linked [Verification handoff](../meet_walk_split_high_probes/verification.Uk6X57/run/result.json). Use for paired outputs, with stage costs reported separately. |
| `walk_together` | Meet_WalkTogether1_pts.mp4, 28.32 s | Distant people, appearance versus entry, shared scene with a later observation | [Whole-video archived run](../meet_walk_evaluation.i2mvYw/run/analysis.json). Its older perception model and incomplete verification make this a historical comparison. |
| `left_bag` | Local 25 s excerpt of LeftBag.mpg, original requested interval [30,55) s, actual [30.0397,55.0397) s | Small object, human handling, partially visible actions | [E1 frame/clip archive](../e1_comparison_001/) and [offline investigation](../e1_offline_investigation_001/analysis.json) cover selected windows around the action. Use them for pilot inspection only. A comparable saved run on the excerpt is missing. |

The 78.28 s set fits the workflow's three 10 s initial windows per recording. The two pedestrian recordings show different sequences from the same camera, so they do not establish camera diversity. Additional local choices are Walk2 (42.24 s), LeftBag_PickedUp (54.24 s), and TwoEnterShop1front (65.80 s). The original MPEGs, normalized MP4s and the 12 s WalkTogether derivative are alternate versions; avoid counting them as independent recordings.

The six local XML files parse using `security_augmented.annotations.parse_annotations`. LeftBag has the project's verified original-video alignment. WalkSplit (623 XML frames / 624 MP4 frames) and WalkTogether (707 / 708) are annotation aids pending their own alignment checks. No automatic offset or conversion from XML hypotheses to gold events is applied. Useful existing utilities include the [E1 evaluation](../../docs/evaluation-protocol.md), the archive controller [comparison](../../src/security_augmented/agent_eval.py), the [retrieval replay](../meet_walk_split_high_probes/retrieval.py), and the source-frame [audit](../meet_walk_split_high_probes/supported-findings-audit.md).

## Freeze the references

Use the [blinded annotation packets and validation commands](annotation_packets/README.md) for the human pass.

1. Use the exact sources and hashes in [cases.json](cases.json). Write two independent annotation files per recording before exposing predictions. Keep originals and an adjudicated file. Use stable reviewer codes. Record disagreement and leave genuine uncertainty ambiguous.
2. Copy [annotation-template.json](annotation-template.json). Set `case`, `source_sha256`, and `reviewers`. Set `review_complete` only after the full case is reviewed, including intervals with no event. Use source-relative half-open integer microseconds. In LeftBag, annotate on the excerpt clock and consult the generated original-frame map to read original timestamps.
3. Each `events` entry has `id`, `category` (existing event category), `description`, `interval: {start_us, end_us}`, `status: supported|ambiguous`, `participants` (local descriptions, or an empty list), `supporting_frames` (each has `display_index`, `pts`, `source_time_us`), and `uncertainty` with any boundary range, visibility or correspondence limitations. Use explicit physical boundary evidence for entry and visible handling for placement or removal. Do not label intent or persistent identity from appearance alone.
4. Freeze a few questions per case before seeing answers. Include a time range, a category question, and a warranted no-answer question. Add a grounded relative anchor where the representation supports it. Each `questions` entry has `id`, `text`, `expectation: answer|abstain|unscorable`, `expected_event_ids` (supported gold IDs for answer), and a short reference rationale. A negative answer must preserve limits of coverage.
5. Generate the review packet, then use [review-template.json](review-template.json). Set all three hashes from the packet. For each stage, map every prediction ID to its adjudicated compatible gold IDs, using an empty list for a wrong or unmatched prediction. Compatibility means the same visible action and distinguishable participant or object under the reference definition. Similar timings and category alone cannot justify a link. Record why an ambiguous case was linked. A transition in subject identity or an unsupported merge is a different event.
6. In `claim_reviews`, use `stage: initial|verification|report`, `prediction_id` (observation or final-event seed ID for the first two, local claim ID for report), `claim`, `reference: supported|contradicted|insufficient`, and `evidence_frames` with the exact source references. Split motion, direction, clothing, identity, and causal statements into atomic claims. Include rendered rationales as attributed assessments and tag that attribution in the review notes. Do not treat an explicit uncertainty statement as a positive claim. Record omitted supported gold IDs and mark `report_checked` after a complete report review.
7. In `retrieval_reviews`, store one entry per question with `id`, `outcome`, `reason`, and reviewer notes on matched events, returned citations, and any unsupported text. Outcomes are `correct`, `justified_abstention`, `partial`, `wrong`, `unsupported_answer`, and `unscorable`. Mark `retrieval_checked` after reviewing all frozen questions.

## Scoring rules

| Metric | Rule |
|---|---|
| Event precision and recall | Score initial positive-category observations and final supported Events separately. An edge requires adjudicated semantic compatibility, same category, and temporal IoU ≥ 0.30. Greedily match in descending IoU, breaking ties by prediction ID and then reference ID. Report TP, unmatched positive predictions (FP), unmatched supported references (FN), and denominators. Duplicate positive predictions are FP. An otherwise unmatched prediction linked to an ambiguous reference with IoU ≥ 0.30 stays excluded with its ID. Unresolved findings never count as positive detections. |
| Temporal localization | On matches, report individual IoU and absolute start/end errors, median IoU and mean start/end error. Use adjudicated central boundaries and preserve boundary uncertainty in the annotation. If uncertainty is large enough to change matching, rescore frozen alternate bounds separately. Very short or one-frame evidence brackets may fail IoU while showing the correct action. Discuss those separately as localization errors and preserve their atomic factual review. |
| Claim-level verification | Cross-tab each human label against the stored completed verdict. Keep `unsupported` and `unfinished` separate. Count reference-contradicted and reference-insufficient claims receiving stored support. Review new errors, narrowed claims, and omissions as separate outcomes. Never conclude that an unfinished check disproved a claim. |
| Citation validity | Check frame membership in the recorded successful inspection, modality, source ID, canonical frame ID, index, PTS, source time, RGB24 hash, and citation interval. Report valid/total references and invalid IDs per stage and unresolved pool. The original archive may lack provider sampling information. Validity does not score semantic relevance. |
| Retrieval | Query-level success is all required reference events returned with valid and relevant citations, correct bracket interpretation and no unsupported claim. A proper explicit abstention counts only where predeclared. Use partial for a subset with sound grounding, wrong for unrelated or missing evidence, unsupported-answer for invented claims, and unscorable where human reference cannot decide. Scores use current local retrieval on frozen inputs, separately from historical answers. |
| Report | Count supported, contradicted and insufficient atomic factual claims, along with omission IDs. Review source citations and elapsed intervals against the saved events and video. Distinguish errors in the report wording from model rationale and errors inherited from Verification. |
| Runtime and usage | Preserve media and role records separately. Report latency distributions or lists, wall time when recorded, logical calls, logged physical attempts and counts of token fields present. Missing fields stay unknown. The Split replay combines separately archived stages and has no single comparable end-to-end elapsed time or physical request total. |

For the contribution comparison use the same gold and the same initial corpus for A and B. Review changed matches and claims per recording. An increase in supported precision may accompany lower recall. Account for triage exclusions, unfinished checks, successful and failed targeted inspections, unsupported claims introduced after inspection, and the actual additional cost. The paired comparison measures the three-agent workflow's effect on these recordings, without attributing differences to a specific agent in isolation. Show counts per video before considering pooled counts.

## Local commands

Run from the repository root. The excerpt and complete original-frame mapping are generated locally with the existing lossless clip extractor. The original recording stays immutable. If the generated directory already exists, use it or reproduce into a fresh directory and compare its hash before use.

```sh
.venv/bin/python experiments/mvp_evaluation/prepare_left_bag.py \
  --output experiments/mvp_evaluation/left_bag_source
.venv/bin/python -m pytest -q experiments/mvp_evaluation/test_score.py
```

After freezing the human files, prepare and score each saved artifact:

```sh
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split \
  --annotations /path/to/walk-split-gold.json > /path/to/walk-split-review-packet.json
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split \
  --annotations /path/to/walk-split-gold.json --review /path/to/walk-split-reviewed.json \
  > /path/to/walk-split-scores.json
```

Use `--case walk_together` with its own files. For LeftBag, supply `--case left_bag --artifact /path/to/saved/analysis.json` after obtaining an authorized run of the hashed excerpt. The blank templates cannot produce scores.

## Remaining prerequisites and runs

Zero new live runs are needed to prepare the method or review the two saved artifacts. **One** additional run supplies the missing LeftBag excerpt for a mixed-version retrospective comparison. **Three** additional runs, one per frozen source, are needed for a uniform prospective comparison using the current model settings, sampling and budgets. Freeze the settings and question set before those runs. Obtain independent annotations, adjudicate disagreement, confirm dataset/provider conditions and explicit transfer authorization, and log complete wall time and attempt counts for the prospective comparison. These three development-exposed recordings support descriptive claims about the MVP rather than held-out generalization.
