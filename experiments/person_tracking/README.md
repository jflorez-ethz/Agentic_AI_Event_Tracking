# Anonymous person tracks within one video: offline pilot

## Closed decision

Conventional person tracking stays outside the MVP. Frozen RF-DETR Nano ×2 with ByteTrack scored **0.616 pooled IDF1 on the original seven test clips** and **0.385 on the three held-out clips**, below the 0.700 acceptance threshold. The five-clip subset scored 0.770. The four owner checks passed on their two designated scenes. The held-out annotations provide no independent evidence of improved event attribution.

On the held-out clips, raw person detection at confidence 0.1 and IoU 0.5 had **6.7% precision and 48.7% recall**. ByteTrack retained 302 of 446 matched observations. Stitching preserved those matches and increased identity credit from 235 to 245. The tracker scored **0.976 pooled IDF1** when supplied with corrected XML boxes. That control changes the tracker inputs as well as the reference and cannot apportion all of the Nano error between detection and association.

**Measurement correction.** The experimental reader now takes all four coordinates from the object's direct `<box>` element. The historical reader could replace its center with a foot landmark. The original seven-clip scores computed with affected references and the historical held-out totals (Nano 0.277, oracle 0.880) are superseded. The earlier attribution of the offsets to the source annotations is withdrawn. Both tuning clips and the five-clip detector comparison used unaffected references. The sections below retain the experimental chronology.

**Reproducibility.** All six held-out source hashes matched the original manifest. Replaying the old reader reproduced the historical Nano metrics and final track summaries on all three clips. The corrected comparison scored identical Nano tracks under both readers and supplied corrected boxes to the oracle. The historical reader, regression tests, frozen configurations, caches and frame exhibits are retained alongside the results. [Source manifest](results_heldout_nano_576x768.json) · [Reference audit](xml_correction.md) · [Original-set corrected results](results_corrected_xml.json) · [Final held-out counts](heldout_audit/counts.json) · [Replay](heldout_audit/audit.py) · [Frame evidence](meet2_audit/frame_195.png)

**MVP boundary.** The production package under `src/security_augmented` runs the Gemini agents and LangGraph workflow independently of the pilot. Production imports and graph routing contain no experimental tracking step. Packaging exposes the older offline pilot's optional `tracking` extra separately from the base and `graph` dependencies. Experimental caches, model weights and track IDs are unnecessary for the MVP workflow.

The pilot assigns "Person A", "Person B"… inside **one** video, from box position and motion only:

1. RF-DETR Nano person detections at 5 fps, cached by `detections.py` (threshold 0.1, with confidences).
2. supervision 0.30.9 ByteTrack, which uses no appearance embedding.
3. Stitching of short breaks at the same place.
4. Removal of tracks that never move (furniture seen as people).
5. Labels in order of first appearance.

There is no face, gait or clothing colour (colour tie-breaking was not tested in this pilot), no link between videos, no model provider call, and no pipeline change.

**Criterion (written before running).** A detection matches an XML box at IoU ≥ 0.5.

1. **Owner test, 4 checks.**
   - LeftBag_PickedUp: the person who sets the bag down and the one who picks it up are one continuous XML track, so they must get the same label.
   - LeftBag_AtChair: they are two XML tracks, so they must get two different labels, each matched to its own track.
2. **Pooled IDF1 ≥ 0.70** over the seven test videos, with RF-DETR detections.
3. The oracle figures (XML boxes used as detections) are reported alongside.

Tuning used Walk2 and LeftBag. The test videos are LeftBag_PickedUp, LeftBag_AtChair, LeftBox, Rest_FallOnFloor, TwoEnterShop1front, Meet_WalkSplit and Meet_WalkTogether1.

**Limit: the owner test rests on two videos only.** PickedUp gives one "same track" case and AtChair one "different tracks" case. LeftBag is a third case but was used for tuning. The CAVIAR XML follows tracks, not people: someone who leaves and comes back gets a new number. The only claim the evaluation can support is "same continuous track", never "same person".

## Result: criterion not met

Frozen settings (Walk2 + LeftBag): activation 0.4, lost-track buffer 1 s, matching 0.8, stitching within 2 s and 20 px plus 40 px/s of gap.

Scores below use the corrected XML reader ([results](results_corrected_xml.json)). Historical values from the foot-landmark reader are in brackets; they are superseded.

| Detections | Pooled test IDF1 (7 videos) | Same, five-clip subset | Owner checks | Test ID switches |
|---|---|---|---|---|
| RF-DETR (main) | **0.501** [0.352] | 0.581 | **2/4** | 10 [4] |
| RF-DETR, no stitching | 0.488 [0.334] | 0.534 | 2/4 | 13 [7] |
| XML boxes (oracle) | 0.942 [0.869] | 0.977 | **4/4** | 5 [20] |

Per video with RF-DETR, IDF1: LeftBox 0.766, Rest_FallOnFloor 0.662, LeftBag_AtChair 0.529, Meet_WalkTogether1 0.498, LeftBag_PickedUp 0.479, TwoEnterShop1front 0.433 [0.002], Meet_WalkSplit 0.262 [0.009]. The tuning videos score Walk2 0.591 and LeftBag 0.528. Only TwoEnterShop1front and Meet_WalkSplit changed; the five-clip subset and the owner checks were never affected.

Owner test with RF-DETR:

| Video | Set down | Picked up | Result |
|---|---|---|---|
| LeftBag_PickedUp | Person C | **Person D** | failed: the track breaks at the pick-up again, as in the earlier tracking pilot (`experiments/tracking_pilot`) |
| LeftBag_AtChair | Person C | **no label** | failed: the person picking the bag up is not detected near the dark furniture |
| LeftBag (tuning) | Person F | Person H | different labels, as expected |

## Findings

1. **Association works when detection is good.** With XML boxes, stitching and the owner test give 4/4 and IDF1 0.942 on the seven test videos (0.977 on the five-clip subset). The bottleneck is detection, as in the tracking pilot: missed people, furniture, plants and mannequins taken for people, and boxes that change while someone bends.
2. **Stitching helps a little:** IDF1 0.488 → 0.501 on seven clips (0.534 → 0.581 on five), and test ID switches 13 → 10.
3. **Withdrawn: "the XML does not align for two test videos".** The offsets reported earlier on TwoEnterShop1front (about 20 px vertically) and Meet_WalkSplit ((−12, −7) px) came from our reader, not from the annotation. Its regular expression let the `xc`/`yc` of body landmarks (head, hands, feet) overwrite the box center. Only XMLs with `<body>` landmarks are affected: TwoEnterShop1front, Meet_WalkSplit, Meet_WalkTogether2 and Meet_Split_3rdGuy. With the direct `<box>` element, the best frame and pixel offset on the held-out clips is 0 frames and ≤ 1 px ([offset search](heldout_audit/diagnosis/offset.json)). Our `_pts` copies are still pixel-identical to the `.mpg` files. See the [reference audit](xml_correction.md) for the list of affected measurements.

## Detector comparison on the five-clip test subset

Each configuration used the same tracking pipeline and parameter grid, tuned on Walk2 and LeftBag and frozen for the five test videos. The pass criterion was pooled IDF1 ≥ 0.70 at IoU ≥ 0.5 and 4/4 owner checks. The clips are 384×288 at 25 fps. Detection sampled every fifth frame and used a confidence threshold of 0.1.

RF-DETR Nano uses 384×384 at its default resolution and `predict(shape=(576, 768))` at twice the source width and height. YOLO26 uses the original decoded frames at both settings and scales internally with aspect-preserving letterboxing. Its `imgsz` goes from 384 to 768, so the image content goes from 384×288 to 768×576.

| Detector | Model size | Enlargement and inference setting | Pooled IDF1 | Owner checks | Detection on CPU (s/min of video) |
|---|---|---|---:|---:|---:|
| RF-DETR | Nano | Baseline, 384×384 | 0.581 | 2/4 | 56.8 |
| RF-DETR | Nano | ×2, 576×768 | **0.770** | **4/4** | 175.7 |
| YOLO26 | n | Original, `imgsz=384` | 0.021 | 0/4 | 8.2 |
| YOLO26 | n | ×2, `imgsz=768` | 0.280 | 0/4 | 20.0 |
| YOLO26 | s | Original, `imgsz=384` | 0.161 | 1/4 | 16.7 |
| YOLO26 | s | ×2, `imgsz=768` | 0.436 | 2/4 | 45.1 |

The timing column is elapsed wall-clock time spent in the per-frame detection call on CPU, including image preparation and detection postprocessing. It excludes video decoding, model loading and tracking. Each value is 60 times the sum of detection seconds divided by the sum of video durations across the five test clips. The original Nano cache had no timings. A separate 384×384 run recorded timings in `detections_stride5_nano_timed.json` and reproduced the original detection rows exactly on all five clips. The other timings come from the detection caches referenced in the six `results_*.json` files.

Nano at 576×768 passed. On LeftBag_PickedUp, the set-down and pick-up both map to Person B. On LeftBag_AtChair, they map to Person C and Person D. YOLO26s at ×2 passed both PickedUp checks and missed both AtChair checks. The RF-DETR Small and Medium trials were conditional on Nano at 576×768 failing the criterion.

Ultralytics 8.4.218 and the YOLO26n/YOLO26s weights were used under AGPL-3.0 for coursework only.

## Validation on three additional CAVIAR sequences

We selected these Edinburgh sequences before scoring and carried forward RF-DETR Nano at 576×768 and all tracker settings from the preceding trial. All three sequences count toward the pooled result. The XML oracle uses the same frozen tracker with annotated person boxes as detections.

Scores use the corrected XML reader. Historical values from the foot-landmark reader are in brackets and superseded; only Meet_WalkTogether2 has body landmarks and changed.

| Sequence | Nano IDF1 | XML oracle IDF1 |
|---|---:|---:|
| LeftBag_BehindChair | 0.531 | 0.959 |
| Walk1 | 0.300 | 0.982 |
| Meet_WalkTogether2 | 0.314 [0.017] | 0.986 [0.689] |
| Pooled | **0.385** [0.277] | **0.976** [0.880] |

The pooled score falls below the 0.70 threshold. LeftBag_BehindChair annotates walkers only, so the owner checks have no independent score on these three clips. The earlier 4/4 applies to PickedUp and AtChair. Integration remains premature.

### Root-cause analysis of the held-out failure

Offline only, on saved caches; nothing was tuned on these clips. Scripts, logs and frame sheets: [heldout_audit/diagnosis](heldout_audit/diagnosis/).

- **Alignment is correct.** Decoded frames = XML frames + 1. PTS have MPEG-1 quirks (a 0.28 s step at frame 0 and compensating +0.08/0.00 pairs) that leave frame indices intact. The best offset between XML boxes and detections is 0 frames and ≤ 1 px on all three clips; median detection−XML residual < 1 px. With the old reader, Meet_WalkTogether2 has no constant offset that works ([offset.json](heldout_audit/diagnosis/offset.json)).
- **Detection misses people; it does not mislocalize them.** Pooled over 915 XML boxes: at confidence ≥ 0.1, precision 0.072 / recall 0.52 at IoU 0.3 and 0.067 / 0.49 at IoU 0.5; at confidence ≥ 0.4, 0.66 / 0.35 at both. Of 469 misses, 285 have no box at IoU ≥ 0.1 and only 32 are boxes at IoU 0.3–0.5. Recall at IoU 0.5 is 0.97 for large, unobstructed walking people, 0.18 for small people (√area < 22 px), 0.17 on static furniture, 0.22 side by side, 0.14 when CAVIAR marks the person inactive, and 0.46 at the image edge (flags overlap). At confidence ≥ 0.4, 96% of false positives are fixed objects (reception desk, a dark object on the floor, a plant pot). In Walk1, XML IDs 4 and 5 (73% of its boxes) sit small behind the glass railing; their best detections reach confidence 0.26 and 0.14, below ByteTrack activation ([detq.txt](heldout_audit/diagnosis/detq.txt), [walk1.png](heldout_audit/diagnosis/walk1.png)).
- **Association is mostly sound.** All final tracks are pure except two in Meet_WalkTogether2. Crediting every spatially correct final box with the right identity bounds pooled IDF1 at 0.474 (vs 0.385), so association costs at most 0.09. BehindChair fragments follow detection gaps longer than the 3 s stitching window ([assoc.txt](heldout_audit/diagnosis/assoc.txt)).
- **Meet_WalkTogether2.** From 13.0 to 15.4 s (frame 340) the two walkers get one merged box; at 15.6 s (frame 390) track 4, which followed XML 2, resumes on XML 1, the only real identity swap. From 22.4 to 33.2 s both stand at the desk, are not detected, and a desk box that moves ≥ 12 px survives the static filter (55 identity false positives) ([meet2_swap.png](heldout_audit/diagnosis/meet2_swap.png)).
- **Detection vs association (counterfactual inputs, same frozen tracker).** Pooled IDF1: XML boxes 0.976; XML boxes only where Nano detects the person 0.550; same with Nano's confidence 0.465; Nano's true-positive boxes 0.466; full Nano 0.385. Missed people dominate, then low confidence on true detections and fixed-object false positives. The split depends on order (the same false positives cost only 0.03 when added to the full oracle), so it is not an exact causal decomposition ([ladder.txt](heldout_audit/diagnosis/ladder.txt)).

The [held-out results](results_heldout_nano_576x768.json) record the frozen settings, source URLs and SHA-256 hashes, per-track counts, and detector timings. Footage and annotations courtesy of the EC Funded CAVIAR project / IST 2001 37540.
