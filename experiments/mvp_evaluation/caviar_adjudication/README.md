# CAVIAR movement adjudication

This packet uses the existing archived predictions and frozen CAVIAR walking references. There are **42 temporal candidate edges** and **two explicit no-candidate rows**. Neither the candidate list nor the preliminary observations below is a semantic adjudication. No precision, recall or F1 is reported yet.

| Case | Full scorer packet | Pair worksheet | Blank scoring review |
|---|---|---|---|
| Meet_WalkSplit | [packet](walk_split.packet.json) | [32 pairs and 2 no-candidate rows](walk_split.matches.csv) | [JSON draft](walk_split.review-draft.json) |
| Meet_WalkTogether1 | [packet](walk_together.packet.json) | [10 pairs](walk_together.matches.csv) | [JSON draft](walk_together.review-draft.json) |

Each worksheet row records the original object ID, walking label, reference frame and time bounds, predicted description and interval, temporal IoU, inspection ID and all cited prediction frame indices with PTS. Reference endpoint PTS, and alignment exceptions in either frame set, are shown separately. Full frame hashes and descriptions are in the packets and immutable [references](../caviar_references/). A blank candidate is a request to inspect the prediction outside the threshold shortlist.

## Candidate summary

Candidate numbers are CAVIAR object IDs, followed by temporal IoU rounded to two decimals. The CSV contains the unambiguous reference-run IDs and exact endpoints. Where both stages are listed separately under one row, see the noted bracket change.

| Case | Model ID prefix | Display bracket, seconds | Temporal candidates | Recorded handoff |
|---|---|---|---|---|
| Split | a0edff0f | 0–1.00 | 0 (.89) | Initial only; deferred |
| Split | 3bfb1c56 | 0–9.52 | 2 (.57), 1 (.46), 3 (.39), 4 (.44), 5 (.33) | Supported, same bracket |
| Split | da6fdebc | 3.52–9.52 | 1 (.43), 3 (.41), 4 (.69), 5 (.45) | Supported, same bracket |
| Split | ac83682f | 10–14.52 | 1 (.32), 3 (.31), 5 (.33), 6 (.51) | Supported, same bracket |
| Split | 83b23ba3 | 10–14.52 | 1 (.32), 3 (.31), 5 (.33), 6 (.51) | Initial only; concurrent movement deferred |
| Split | 7f18178d | 16.52–19.52 | 7 (.36) | Initial only; deferred |
| Split | 433e1420 | 20–24.52 | None at threshold | Supported, same bracket |
| Together | 075f06c9 | 10–13 | 1 (.39), 2 (.68) | Supported, same bracket |
| Together | 229b46c5 | Initial 13–19; verified 17–19 | Initial 2 (.72), 1 (.63); verified 2 (.36), 1 (.31) | Supported with narrower bracket |
| Together | 1745a5f3 | 27–28 | 6 (.30), 3 (.41) | Initial only; association remains unresolved |

## Preliminary stage comparison

- **WalkSplit:** All four delegated movement candidates reached supported verdicts. The three omitted movement observations were deferred, so the reduction from seven to four is driven by triage. They each have a temporal candidate and may represent real movements. The 10–14.52 s pair of observations has the same temporal candidates because their brackets coincide, despite model descriptions suggesting two distinct paths. The 3.52–9.52 s final rationale narrows the initial claim to diagonal motion, so review whether that removes an unsupported joining interpretation.
- **WalkSplit 20–24.52 s:** The recorded supported verdict remains intact in the packet. It has no walking reference at IoU ≥ 0.30. The earlier [visual audit](../../meet_walk_split_high_probes/supported-findings-audit.md) separately judged the cited views insufficient for a reliable left-to-right traversal because of glare and occlusion. The targeted clip returned no observations. Failure to qualify under the XML matching rule and visual insufficiency are separate findings. Determine the annotation scope and exact visible claim before labeling the event a false positive.
- **WalkTogether:** Two of three movement observations survive as supported. One bracket narrows from 13–19 s to 17–19 s, reducing its IoU with both candidates. This may reflect a narrower evidence claim rather than a new perceptual error. The 27–28 s observation remains unresolved after association. A supported appearance event and an unfinished appearance check appear in the full packet, outside the walking denominator.
- **Provenance:** All 16 projected prediction citation references resolved against successful inspection membership, source frame ID, PTS, timestamps and RGB hashes. The review did not independently establish the correctness of the model claims. The Split archive used Gemini 3.6 Flash HIGH / 8192 for perception and Verification; the Together archive used Gemini 3.5 Flash-Lite LOW / 4096 for perception. Role settings available from the archives are retained in the packets. Compare the stages within each video before comparing across videos.

## Review and score

1. Copy each CSV and its review draft before filling it. For each proposed pair, open the local source and compare the model description and cited frames with the original XML boxes and trajectory for that specific object ID. Review the claimed action and person separately from timing. Mark `same_visible_movement`, `different_movement`, `uncertain`, or `unlabelled_region` in the worksheet, with a reason and decisive source indices. Check the no-candidate rows too. Do not use the largest IoU to select the person. Review direction, identity, interaction and other modifiers as separate claims.
2. Transfer adjudicated same-event reference IDs to `event_links` for the correct stage. Use `[]` only for a reviewed, in-scope prediction with no valid link. Put genuinely unlabelled-region predictions in the existing `caviar_unlabelled_predictions` map with an evidence-based reason and omit them from `event_links`. If identity or alignment remains uncertain, keep the worksheet judgment and review draft pending. Withhold the affected primary scores rather than interpreting pending links as false positives or false negatives. Preserve the held-out rows and reasons in the review record.
3. Set the reviewer code. For independently assessable claims, fill `claim_reviews` using the [evaluation protocol](../README.md) and cite review frames. Keep the original annotations and the three hashes in the review draft. After adjudication, the same greedy descending-IoU one-to-one rules and threshold apply to both stages. The scorer rejects pending or unknown links. It reports precision, recall, F1, matched IoU and endpoint errors, plus citation integrity and available claim judgments.

From the repository root, regenerate into a fresh directory if needed:

```sh
packets=$(mktemp -d /tmp/sa-caviar-adjudication.XXXXXX)
refs=experiments/mvp_evaluation/caviar_references
for case in walk_split walk_together; do
  .venv/bin/python experiments/mvp_evaluation/score.py --case "$case" --caviar-reference \
    --annotations "$refs/$case.reference.json" > "$packets/$case.packet.json" || exit
done
.venv/bin/python experiments/mvp_evaluation/prepare_caviar_review.py "$packets"
```

Use the completed review files to score:

```sh
refs=experiments/mvp_evaluation/caviar_references
for case in walk_split walk_together; do
  .venv/bin/python experiments/mvp_evaluation/score.py --case "$case" --caviar-reference \
    --annotations "$refs/$case.reference.json" --review "$case.reviewed.json" \
    > "$case.scores.json" || exit
done
```

The local XML copies remain unverified byte-for-byte against the publisher. WalkTogether flags original indices 62, 157, 310, 312 and 566 for near-neighbor alignment ambiguity and index 64 for missing original PTS. These are development-exposed recordings. Group relationship labels remain outside movement scoring, and natural-language answers still need human references. This review changes no production model, validator or archived verdict.
