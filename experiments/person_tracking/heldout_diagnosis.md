> **Status: superseded.** This note predates the reader correction and the full root-cause analysis. See the [README section](README.md#root-cause-analysis-of-the-held-out-failure) and [heldout_audit/diagnosis](heldout_audit/diagnosis/).

## Frozen Nano ×2 audit of the three held-out clips

The saved JSON contains final track counts, time spans and per-XML-ID match counts. The previous run downloaded the originals and wrote its detection cache inside a temporary directory. Neither those six inputs nor the held-out frame-level cache is present locally. Source URLs and expected SHA-256 hashes are in [the run manifest](results_heldout_nano_576x768.json). The official download failed at DNS resolution in this session.

| Clip | XML boxes | Final boxes | Frame matches reported by pilot | IDTP | IDFP | IDFN | Switches |
|---|---:|---:|---:|---:|---:|---:|---:|
| BehindChair | 305 | 136 | 136 | 117 | 19 | 188 | 2 |
| Walk1 | 312 | 55 | 55 | 55 | 0 | 257 | 0 |
| Meet_WalkTogether2 | 298 | 167 | 4 | 4 | 163 | 294 | 0 |

Walk1 loses all 115 sampled instances of XML ID 4 and all 110 of ID 5. Every retained box receives identity credit. BehindChair has 19 fewer identity-credited boxes than frame matches, with two different output labels each for XML IDs 0 and 2. Raw detections are needed to distinguish confidence filtering, track suppression, localization and detector misses.

In Meet_WalkTogether2 the four output tracks span 0–4.36, 7.76–18.56, 8.76–18.16 and 22.36–33.16 seconds. XML IDs 0, 1 and 2 receive 3/25, 0/141 and 1/132 per-frame matches. Even optimal reassignment of identities on every frame could credit at most 16 of 167 retained boxes at the pilot's IoU threshold with the recorded alignment. The 3×4 trajectory overlap-count matrix can be padded to 4×4 and partitioned into four disjoint permutation diagonals. Each diagonal sums to at most the globally optimal IDTP of 4. This bound concerns final boxes only.

The earlier XML-box run on Meet retained 268 of 298 inputs and credited 195. ByteTrack returns selected input boxes, stitching relabels them and static filtering removes tracks. Restoring source identities to the retained XML boxes would therefore score 536/566 = 0.947. Relative to perfect coverage, 30 instances are missing and 73 retained instances lose credit under global identity assignment. The individual stages responsible remain unresolved.

XML trajectories passed directly through the pilot scorer scored 1.000 on all nine locally available original-pilot clips. An independent exhaustive track assignment on LeftBag_PickedUp reproduced 189 IDTP, 0 IDFP and 24 IDFN. The per-frame switch diagnostic maximizes summed IoU before thresholding, which can discard feasible matches. A synthetic two-person example with IoU rows [0.818, 0.429] and [1.000, 0.538] yields one match under that procedure and two under threshold-first matching. This diagnostic is separate from global IDF1.

The smallest discriminating replay is Meet_WalkTogether2 alone, preserving raw detections and all existing stage outputs. Start with overlapping output tracks at 8.76 s and inspect native frames around that timestamp with XML, raw detection and final boxes. Check nearby frames and static scene landmarks for a reproducible annotation offset. If raw boxes align with XML but vanish before the final output, isolate the first stage that loses them. No frame-level visual cause, held-out detector precision or recall, or improvement in event attribution has been established.
