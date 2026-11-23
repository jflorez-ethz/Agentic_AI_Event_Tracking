# Source-video delivery review

Two frozen outputs from the existing evaluation manifest were checked against their original MP4 files. Meet_WalkSplit uses a real archived scan and a later live Verification continuation. Meet_WalkTogether1 uses an archived full three-agent run with different model settings and 1-second sampling. These are development sequences from the same overhead atrium camera. They test different visible activities. They provide little evidence about performance on other camera installations.

| Archived run | Initial observations | Recorded supported events | Unresolved records | Final citations verified, including unresolved | Distinct cited frames |
|---|---:|---:|---:|---:|---:|
| WalkSplit | 11 | 4 | 7 | 11/11 | 48 |
| WalkTogether1 | 5 | 3 | 2 | 5/5 | 13 |

The checks pin the archive and video SHA-256, decode the cited MP4 frames with FFmpeg, and check inspection membership, canonical ID, PTS, source-relative time, display index and RGB24 hash. The sheets show original-size samples, with JPEG compression for display. The recorded hashes refer to the decoded source pixels. Complete canonical references and local question responses are in the two JSON files. [WalkSplit sheet](walk_split/source-samples.jpg) · [results](walk_split/result.json) · [WalkTogether1 sheet](walk_together/source-samples.jpg) · [results](walk_together/result.json)

## Provisional assessment of all seven supported claims

| Video and verified bracket | What the footage supports | Limitation or omission |
|---|---|---|
| Split 0–9.52 s | Figures change position from the sunlit aisle onto the floor. See indices 0, 125, 238. | Glare limits clothing detail. Which earlier person corresponds to which later silhouette remains uncertain. |
| Split 3.52–9.52 s | Diagonal movement and decreasing image-plane spacing are visible between indices 88, 125, 163. Two figures are close at 163. | The archive verifies individual movement. The observation's “joining” interpretation goes beyond the visual evidence. The four-event timeline omits the local approach as a separately queryable event. |
| Split 10–14.52 s | Two silhouettes have distinguishable paths near the corridor and seats at indices 250 and 313. The corridor motion is plausible from the cited frames. | The individually deferred seating movement is a coverage loss. The partially obscured endpoint at 363 and the earlier overlap leave same-pair continuity open. The model rationale also refers to a clip outside the final frame citations. |
| Split 20–24.52 s | The bright glass-roofed area contains a small dark/purple feature at indices 500, 563 and 613. | A left-to-right traversal cannot be confirmed against the crossbars. The supported movement remains disputed in this archive. |
| Together 10–13 s | A blue-topped figure changes position from upper right to center between indices 250, 300, 325. | The interval brackets samples. It does not establish the onset or end of the complete walk. |
| Together 17–19 s | Figures move near each other toward the upper-left doorway, indices 425, 450, 475. | The candidate citation begins at 13 s, earlier than the selected transition. The model's description of a meeting and interaction in the center concerns earlier images. The supported Event category establishes movement only. |
| Together 27–28 s | Two people are already visible near the upper-left entrance at index 675. Their positions change by 700. | The pair of cited images fails to show an absent-to-visible transition for these two people. The recorded supported appearance verdict is questionable. Enlarging index 650 (26 s) supplies earlier context outside the cited interval. The associated movement remains unresolved, despite visible displacement. |

The 9 s Together appearance check has a single cited frame. Leaving its transition unresolved is appropriate. No verified identity links or same-pair separation were produced in these two timelines. For the other WalkSplit experiment's accepted approach marks, an archived model proposal passed the current relational validator on offline replay. Partial silhouette overlap limits the endpoint geometry. That replay is a separate result. [Proposal and source review](../../relational_motion/visual-grounding-audit/approach-source.png) · [Detailed movement audit](../../meet_walk_split_high_probes/supported-findings-audit.md)

## Local retrieval check

The same three questions were run through the current Analysis.ask method for both archives. “What happened between 10 and 15 seconds?” returned the 10–14.52 s movement in Split and the 10–13 s movement in Together with their original frame citations. In both archives “What happened after the two people approached each other?” returned no grounded matching anchor. “Did the two people separate afterward?” returned insufficient evidence for continuity. Neither archived timeline contains an independently validated relational anchor. An unanswered question can accurately reflect this gap.

## Reproduction and independent review

From the repository root, use a new output directory.

```sh
.venv/bin/python experiments/mvp_evaluation/delivery_review.py --output /tmp/sa-delivery-review
ffmpeg -v error -i data/raw/Meet_WalkTogether1_pts.mp4 -vf "select='eq(n,650)+eq(n,675)+eq(n,700)',crop=135:100:0:20,scale=405:300:flags=neighbor,tile=3x1" -frames:v 1 /tmp/sa-together-appearance.png
```

Independent human adjudication is still pending. The [existing review interface](../visual_review/index.html) displays the archived predictions and CAVIAR candidate movements and collects reviewer decisions. The two source sheets above are label-free for a first viewing. Review the endpoints independently before reading the model rationales. Keep the two disputed verdicts as recorded in the archives. Precision, recall, semantic accuracy, and identity error rates require independently adjudicated targets. The timing displayed here measures citation brackets, with no claim of independently measured localization error.
