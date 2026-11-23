# Paired 2 FPS / 4 FPS source audit

Source: data/raw/Meet_WalkSplit_pts.mp4. Recorded arms: [500 ms](sampling-live.4GdQOj/step-500/result.json) and [250 ms](sampling-live.4GdQOj/step-250/result.json). The input manifests match the frozen plans. The 30 sparse frames are identical to the even-position subsequence (zero-based) of the 60 dense frames. All 60 unique display indices, PTS and RGB24 hashes were replayed from the source. The raw JSON responses validate independently against their saved schemas, and every raw frame label resolves in order to the corresponding stored observation citation. Matched inputs do not reveal the provider's internal image processing.

| Recorded field | 500 ms | 250 ms |
|---|---:|---:|
| HTTP / physical sends | 200 / 1 | 200 / 1 |
| Candidate / finish / validation | 1 / STOP / passed | 1 / STOP / passed |
| Recorded errors | None | None |
| Prompt tokens | 32,618 | 65,038 |
| Thinking tokens | 2,444 | 4,657 |
| Candidate tokens | 461 | 1,306 |
| Total tokens | 35,523 | 71,001 |
| Reported elapsed time | 21.604 s | 41.582 s |
| Observations | 2 appearance, 2 movement | 3 appearance, 3 movement, 1 insufficient-evidence |

## Claim-to-frame comparison

Indices are source display indices. Time base is 1/12800. For example, index 125 has PTS 64000. The archived input manifests provide the full canonical frame IDs and hashes.

| Claim | 500 ms output | 250 ms output | Provisional local source judgment |
|---|---|---|---|
| Initial people | Two “become visible” at F1. | Two separate first-visible descriptions at F1. | Shared frame 125 (5.00 s) shows two distinguishable walkers, one near the left and one toward the lower right. Neither begins a visibility transition in this one frame. The dense arm usefully separates their initial positions. Clothing descriptions are too similar to function as stable identifiers. |
| Apparent convergence | No distinct convergence claim. F1–F20 refers broadly to both moving toward the upper-left hallway. | Two motion descriptions, one stating that a person moves to meet the other. An insufficient-evidence observation cites F5–F7 (indices 150, 157, 163) for close proximity and unclear hand activity. | At 150 / 6.00 s (shared), 157 / 6.28 s (dense-only), and 163 / 6.52 s (shared), positions visibly draw closer. The sequence shows movement, so “stand close together” is an imprecise description. Apparent convergence is supported, while purpose, contact and object exchange remain unestablished. The new frame 157 supplies an intermediate view; the shared endpoints already show the trend. |
| Overlap and continuity | Broad two-person claim does not explicitly resolve identities. | Separate named-by-clothing trajectories both cite F1–F40 and say movement between samples is unobserved. | Dense-only 169 / 6.76 and 182 / 7.28 s provide closer spacing around shared 175 / 7.00 s, where the silhouettes overlap. Shared 188 / 7.52 s again shows distinguishable figures. The model did not specify an identity anchor through overlap. A sampling disclaimer does not validate the two trajectories. |
| Later paths | F1–F20 (125–363, 5.00–14.52 s): broadly upper-left. | Both F1–F40 (125–369, 5.00–14.76 s): upper-left corridor, with stronger “walk together” language. | At shared 250 / 10.00, 300 / 12.00 and 325 / 13.00 s, the group is moving toward the left in broad terms and the paths near the corridor and seats are distinguishable. Neither answer explicitly identifies the divergence. The stronger common-destination narrative loses that distinction. Dense-only endpoint 369 / 14.76 s is not a clear individual continuity anchor. |
| Later walkway | First visibility at F24 (413 / 16.52 s), movement through F30 (488 / 19.52 s). | First visibility at F38 (357 / 14.28 s), movement through F60 (494 / 19.76 s), with light shirt claim. | Movement near the sunlit left walkway is clearer later, including 413 and 425 / 17.00 s. Crops of 350, 357, 363 and nearby frames show glare, structure and small shapes. They do not settle an exact onset at 357, clothing or a continuous connection to either earlier walker. Both appearance records cite one frame each. The 2.24 s onset difference is a discrepancy, not a measured gain in timing accuracy. |

Blinded independent review was unavailable. These judgments are provisional and no reviewer agreement is reported. One response per arm cannot isolate sampling density from model variability. In particular, a useful observation that cites a dense-only frame does not establish that Gemini needed that frame to make the observation.

Retain 2 FPS as the default for this workflow. The dense response adds a more explicit convergence cue and a cautious statement about fine contact, while providing no validated continuity or separation and increasing input by nearly 2× and elapsed time by about 92%. Consider 4 FPS for a short, predeclared overlap window only if a follow-up uses independently annotated correspondence/abstention criteria. No external calls, reruns, or production changes were made in this audit.

## Reproduce local views

Resolve the raw frame labels through the arm's input JSON array, then verify each cited index with the project video decoder and RGB24 SHA-256. The following crop is an enlarged inspection view and does not alter the submitted files:

```bash
ffmpeg -v error -i data/raw/Meet_WalkSplit_pts.mp4 \
  -vf "select='eq(n,350)+eq(n,357)+eq(n,363)+eq(n,375)+eq(n,394)+eq(n,400)+eq(n,406)+eq(n,413)+eq(n,425)+eq(n,488)',crop=185:115:0:142,scale=370:230:flags=neighbor,tile=5x2" \
  -frames:v 1 /tmp/sa-pair-walkway.png
```
