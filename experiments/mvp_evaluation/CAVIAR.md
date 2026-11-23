# CAVIAR evaluation references

Dataset credit: EC Funded CAVIAR project / IST 2001 37540. The official [Edinburgh sequence index](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/) identifies the files and the [XML grammar](https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/gt_file_format.txt) defines frame-level geometry, persistent sequence-local identities, members, and separate movement, role, situation and context labels. The publisher notes annotation boundary variability and unlabelled lobby areas.

## Inputs

| Sequence | Publisher file | Local copy | XML frames | Local SHA-256 |
|---|---|---|---:|---|
| Meet_WalkSplit | [mws1gt.xml](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/Meet_WalkSplit/mws1gt.xml) | data/annotations/mws1gt.xml | 623 | a3f76c5f9539d9bff4730863d503ce979c5dfe5e9595689578eedd4d6bbd790b |
| Meet_WalkTogether1 | [mwt1gt.xml](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/Meet_WalkTogether1/mwt1gt.xml) | data/annotations/Meet_WalkTogether1.xml | 707 | cb8cdb35b04c590503e25a5ef3b9fb96eedb90a9e3af3208caa3cbc35ae63092 |
| LeftBag | [lb1gt.xml](https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/LeftBag/lb1gt.xml) | data/annotations/LeftBag.xml | 1439 | 9599de02b41369065f1c718ec9c934bf1d58b65dc969b88e36c08ca54ab52bb7 |

The publisher links are confirmed. The browser rejected the XML content type and direct downloads failed on DNS. Local files were preserved unchanged. Their byte-for-byte equivalence to the current publisher files remains unconfirmed. The sidecars record the original filename, URL, digest, sequence name, object and group IDs, label inventory, frame mapping and QC flags. The original XML retains unmodified geometry, orientation, appearance, and hypothesis metadata.

## Alignment and visual checks

- **WalkSplit:** Original MPEG and processed MP4 both decode to 624 presentation frames. All 624 same-index luma matches beat neighbors within ±2, with maximum same-index mean absolute luma error 0.661 on the 0–255 scale. RGB hashes differ after processing. Mapped XML overlays at indices 100, 150, 185, 251 and 300 follow the figures around joining, interaction, walking and split. XML indices 0–622 map to same-index local PTS at time base 1/12800. Index 623 is unlabelled.
- **WalkTogether:** Both streams decode to 708 frames. Same-index luma wins at 703, with maximum same-index mean absolute error 0.632. Indices 62, 157, 310, 312 and 566 have a closer neighbor within ±2 and remain flagged. The MPEG has no raw PTS at index 64. The sidecar preserves null original PTS there and records the local MP4 PTS. Overlays at XML indices 300, 350, 400, 650 and 700 support the same-index mapping around meeting and walking. XML indices 0–706 map to local PTS at 1/12800; index 707 is unlabelled. Fifteen boxes extend outside the image and remain unchanged.
- **LeftBag:** The existing hash-pinned LeftBag alignment maps indices 0–1438 of the 1440-frame MPEG. The lossless clip validator rechecked every excerpt frame and timestamp. Excerpt indices 0–624 map to original 745–1369, original source interval [30.0397,55.0397) s. Local PTS use 1/1000. The published group interval [945,997) maps to local [8.00,10.08) s. Overlays at original indices 900, 925, 950, 967 and 980 show the person by the bench and the bag separately boxed in later frames. This label does not give the exact physical placement boundaries.

No dropped, duplicated or reordered decoded positions were established between the pedestrian originals and their MP4s. The tests support the local presentation-order mapping rather than publisher JPEG equivalence or exact hand-label boundaries. QC found no out-of-image box centers, duplicate entity IDs in a frame or groups with absent members. Frame counts alone were not used as alignment evidence. The overlays are local spot checks without independent adjudication.

## Category compatibility

| Scope and observed labels | MVP mapping |
|---|---|
| Individual movement walking | Broader person_moved. One run per individual track segment. Direction and relationships are not inferred. |
| Individual movement active/inactive, situation moving/inactive/browsing, role walker/browser/leaving object, context walking/browsing/immobile | Unmapped as standalone events. Preserve in the sidecar. |
| Object and group appearance appear/visible/disappear | Unmapped. Track lifecycle does not guarantee a supported visible before/after or physical crossing. |
| Group situation joining/interacting/moving/split up, role meeters/walkers, context meeting, movement movement/active | Unmapped relational annotation. Preserve independently of individual movement. |
| Group situation leaving object and context leaving | Unmapped. These broader labels do not isolate placement, removal or abandonment. |

The XML contains per-frame object/group lists and center-based boxes. The converter splits consecutive runs on annotation gaps, ID, group membership, hypothesis or label changes. It uses the next local presentation frame as the exclusive end and clips references to the available excerpt. WalkSplit group 0 retains joining [100,169), interacting [169,195), moving [195,281), split up [281,301). WalkTogether has joining, interacting and moving but no split situation. LeftBag retains the leaving-object group interval in scope; the untrimmed XML also contains moving, interacting and split up. There is no direct, lossless event equivalence. Unsupported labels stay in the provenance inventory.

## Preliminary offline results

| Case | Walking references | Initial movement claims with a temporal candidate | Final supported movement claims with a temporal candidate |
|---|---:|---:|---:|
| WalkSplit | 9 | 6 of 7 | 3 of 4 |
| WalkTogether | 8 | 3 of 3 | 2 of 2 |
| LeftBag excerpt | 2 | No saved excerpt run | No saved excerpt run |

Candidates use same category and IoU ≥ 0.30, with no assignment or semantic credit. These counts are leads for reviewers rather than precision or recall. Multiple claims can overlap the same track, and an unlabelled region is not automatically a false positive. The scorer keeps the existing one-to-one rules and requires adjudicated semantic links, including correct individuals. It excludes other model categories from the walking denominator and records their counts. For a reviewed prediction in an unlabelled area, record its ID and reason in the stage’s caviar_unlabelled_predictions map instead of an event link. The scorer records these exclusions outside the precision denominator. Report unmapped group runs separately as coverage gaps. Claim-level Verification and unsupported details still need human source review. The XML does not create question-answer references. The three cases are development-exposed and support descriptive evaluation.

From the repository root:

```sh
ref_dir=experiments/mvp_evaluation/caviar_references
.venv/bin/python experiments/mvp_evaluation/caviar.py --output /tmp/caviar-reference-replay
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split --caviar-reference \
  --annotations "$ref_dir/walk_split.reference.json" --validate-only
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split --caviar-reference \
  --annotations "$ref_dir/walk_split.reference.json" > walk-split-caviar-packet.json
.venv/bin/python experiments/mvp_evaluation/score.py --case walk_split --caviar-reference \
  --annotations "$ref_dir/walk_split.reference.json" --review walk-split-caviar-reviewed.json
```

Repeat with walk_together. LeftBag validates now and needs an exact-excerpt saved artifact for scoring. Use the existing review template. All reference data and output changes stay in the evaluation directory. No Gemini calls or video transfers occurred.
