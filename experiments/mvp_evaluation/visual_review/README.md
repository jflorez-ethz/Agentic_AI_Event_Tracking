# Local CAVIAR visual review

Open [index.html](index.html) as a local file. Keep it beside the scripts and assets. No server, browser extension, account or network connection is required.

From the repository root:

```sh
xdg-open experiments/mvp_evaluation/visual_review/index.html
```

The blank set contains 42 temporal candidate pairs (32 WalkSplit, 10 WalkTogether) and two no-candidate rows. Original CAVIAR labels and archived Gemini findings are shown as distinct evidence layers. There are no default judgments.

## Review

1. Select the video, a reviewer code, and a prediction. Initial and verified versions have separate entries so a changed bracket or rationale gets its own judgment.
2. Select each CAVIAR candidate above the evidence panels. Step through the numbered source frames. The left panel uses the recorded prediction citations. The right panel shows up to five source frames within the temporal overlap, with the original CAVIAR object's box drawn as an overlay. The source PNG is unaltered. Frame index, PTS and source-relative timestamp appear under each image. Use the local source video and the detailed worksheet for additional context as needed.
3. Mark **Match**, **No match**, or **Uncertain** and optionally record a reason. IoU is a shortlist criterion. Compare the movement and the specific visible person. For the two no-candidate predictions, review the cited source and explicitly choose the no-match or uncertain outcome. If a prediction is outside the CAVIAR labelling scope, document why in the unlabelled-region field. Its exclusion is recorded separately by the scorer. Resolve any recorded match before excluding that prediction.
4. The browser saves locally where supported. **Save draft** exports a portable JSON for the selected video. It preserves comments, uncertainty and pending decisions. Use **Import review** to resume or revise it. Use separate browser profiles or private windows for independent reviewers. Keep each reviewer's files under a distinct name before adjudication. Save both videos separately.
5. **Export for scoring** becomes available for the selected video after a reviewer code and all required judgments are present. An uncertain judgment stays pending for scoring. Resolve it by further review, or withhold the affected scores. A score-ready JSON uses the existing scorer fields and retains the per-pair browser decisions in an optional metadata field for import. No JSON editing is needed.

The uncertainty rule prevents an ambiguous correspondence from becoming an empty link list and a potential false positive. The existing scorer retains one-to-one assignment. A score-ready export covers movement adjudication. Claim-level and natural-language judgments still use the separate evaluation protocol.

## Reproduce assets and score

Build from the frozen scorer packets using the existing CAVIAR parser, source mapping, and FFmpeg decoder:

```sh
.venv/bin/python experiments/mvp_evaluation/visual_review/prepare.py
.venv/bin/python -m pytest -q experiments/mvp_evaluation/visual_review/test_visual_review.py \
  experiments/mvp_evaluation/test_score.py experiments/mvp_evaluation/test_caviar.py
```

Prediction images must match the archived decoded hashes and provenance fields. Reference images use the verified local video identity and mapped timestamps and receive locally computed RGB24 hashes. Warning banners preserve the recorded WalkTogether alignment exceptions and missing original PTS. Missing or unreliable mappings are reported in the affected reference panel.

After adjudication, substitute your downloaded reviewer-specific filename:

```sh
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split --caviar-reference \
  --annotations experiments/mvp_evaluation/caviar_references/walk_split.reference.json \
  --review /path/to/walk_split.reviewer-01.reviewed.json > walk_split.scores.json
```

Use the analogous case and reference paths for `walk_together`. The result contains precision, recall, F1, match details and citation checks.
