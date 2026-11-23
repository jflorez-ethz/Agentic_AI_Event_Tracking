# Offline first-visibility decision audit

| Decision | Evidence and assessment | Classification |
|---|---|---|
| 9 s, rejected | Seed cites display index 225 only (PTS 115200, 9 s). Targeted [8,10) s inspection returned a same-category observation citing indices 200 and 225 (PTS 102400 and 115200, 8 and 9 s). The trace records accepted correspondence using shared frame 225. | A pair was available. The validator correctly rejected an out-of-observation frame reference. The exact original field is unknown. |
| 27–28 s, accepted | The recorded pair is 675 and 700 (PTS 345600 and 358400, 27 and 28 s). A figure is already discernible near the corridor in the first image. A second figure's earlier visibility is indeterminate in the pair. Both are clearer later. | The citation supports movement into clearer view. First visibility of two people is too strong. This is a provisional semantic finding. |

The full observation and frame IDs, extracted-input memberships, recorded decision trace, source hash and decoded RGB24 hashes are in [the manifest](evidence-manifest.json). The source time base is 1/12800 s. FFprobe presentation timestamps agree with the source ingestion record. FFmpeg decoded the selected frames at native 384 × 288 resolution, with source PTS verified in the decode. The original structured 9 s verdict was not preserved.

## Controlled 9 s replay

The reconstructed payload selects the seed and the targeted observation and reuses the recorded same-event assessment and its exact excerpts. Its claim and pair are fixed at first visibility over frames 200 and 225. When the pair's observation ID points to the seed, frame 200 is outside that citation and the validator reproduces “Transition frames are outside the cited observation.” Changing only the pair's observation ID to the targeted observation passes the existing validator and produces the source bracket [8,000,000, 9,000,001) µs. The reference-only repair is an admissible alternative, not recovery of the original model payload. Other malformed combinations could have produced the same logged error.

## 27–28 s citation review

In the before frame, the leading figure is discernible in the upper-left corridor-side area. For the second figure, the darker shapes farther back do not establish an unambiguous match to the later figure in the pair alone. In the after frame, both figures are discernible as they move farther into view. Consecutive source frames 650–707 (26–28.28 s) make the ongoing movement and partial visibility clearer. They do not establish that both people were absent from view at 27 s. This exposes the weakness of reading clearer visibility as first visibility.

Two independent blinded reviewers were unavailable. Agreement is unmeasured. The separate [review packet](blinded_pair/) contains native-resolution images and a rubric without model labels or conclusions. Present the pair first and record each person's classification before revealing the surrounding sequence.

## Disposition and reproducibility

The first failure concerns reference binding despite available admissible evidence. The second reflects semantic overstatement despite a structurally valid pair. Neither replay isolates a schema or validator defect. No production code, budgets, prompts, or historical artifact changed. No data was transferred.

From the repository root:

```sh
.venv/bin/python experiments/meet_walk_first_visibility_audit/replay.py
.venv/bin/python -m pytest -q tests/test_person_claims.py tests/test_visual_transitions.py tests/test_inspection_recovery.py tests/test_evidence_semantics.py
```

31 focused offline tests passed.
