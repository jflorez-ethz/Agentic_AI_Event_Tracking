# Left / removed / still-present objects: offline pilot (detector C1, objects)

`pilot.py` uses dual background subtraction (OpenCV MOG2, slow vs fast) with a person filter. It has no model provider call and handles no identity. Person boxes come from RF-DETR Nano at 5 fps (`persons.py`, cached), from the CAVIAR XML (perfect filter), or from no filter.

**Criterion (fixed before running).** An event is found when its type matches, its time is within ±2 s of the XML (PTS) and its position within 20 px. Success requires all of:

- the three placements found;
- the LeftBag_PickedUp removal found;
- LeftBox reported as still present at the end;
- **0 false alarms** on the five videos without an object (201.9 s in total); the raw count is reported.

LeftBag is the tuning video only.

Ground truth: LeftBag placed 38.04 s, removed 54.44 s; LeftBox placed 23.08 s, present at end; LeftBag_PickedUp placed 20.36 s, removed 40.88 s.

## Result: criterion not met

Parameters frozen on LeftBag: T = 3 s, minimum area 60 px².

| Person filter | fps | Test events | False alarms, no-object videos | False alarms, object videos |
|---|---|---|---|---|
| RF-DETR (main) | 25 | 3/4 | 20 | 15 |
| RF-DETR | 5 | 3/4 | 22 | 19 |
| XML (perfect) | 25 | 3/4 | 14 | 15 |
| XML (perfect) | 5 | 3/4 | 16 | 21 |
| none | 25 | 3/4 | 22 | 21 |
| none | 5 | 3/4 | 22 | 25 |

Main configuration per video:

| Video | Result |
|---|---|
| LeftBox | placed (1.36 s error) and present at end found; 4 false alarms |
| LeftBag_PickedUp | **removal found (0.8 s error)**; the placement was detected at the right place but 2.56 s early (17.8 s), so it counts as missed |
| TwoEnterShop1front, Meet_WalkTogether1 | 0 false alarms |
| Rest_FallOnFloor | 6 false alarms |
| Walk2 | 8 false alarms |
| Meet_WalkSplit | 6 false alarms |

CPU time is about 6 s per video minute, excluding RF-DETR.

Sensitivity to T, with the RF-DETR filter at 25 fps:

| T | Test events | False alarms, no object | False alarms, with object |
|---|---|---|---|
| 2 s | 3/4 | 22 | 15 |
| 3 s | 3/4 | 20 | 15 |
| 5 s | 0/4 | 16 | 10 |
| 8 s and 12 s | 0/4 | 0 | 0 |

## Diagnosis

1. **Startup ghosts.** These are 18 of the 20 main false alarms. The slow model learns the first frame, including the people in it, so their vacated place later looks like a new still object: placed at 0.0–0.4 s, then present at the end at the same spot. The same effect appears on LeftBag, the tuning video. The sheets confirm it (for example candidate 13).
2. **Mis-calibrated slow model (implementation flaw).** The slow model is set to a 60 s history, but MOG2 turns a new colour into background once it holds about 10% of the weight (backgroundRatio 0.9). That happens after roughly 6 s, so a still object counts as "static" for only 2–6 s, and every T ≥ 5 s finds nothing.
3. **People standing still.** The remaining 2 false alarms are the Walk2 pair that stands still for about 34 s, which RF-DETR misses.
4. **Placement timing.** The detector dates the area change while the bag is being set down; the XML marks the bag once it is separate.

A next iteration should fix 1 and 2 on the tuning video alone, using principled settings: a slow model absorption time longer than the longest expected stay, and a ghost test such as no edges in the current frame or a warm-up. Freeze them, then re-measure the held-out videos unchanged.

## Review material

`sheets/candidate-NN.png` shows before, at and after crops (±3 s). `blind_review.csv` lists time and place without the detector's label, for blind labelling. Results are in `results_main.json` and `results.json`.

## Trial 2: second attempt after seeing trial 1's test results

**Read this as a second attempt, not a clean held-out result.** The two fixes below were chosen after trial 1's test and no-object results had been seen. Parameters were then tuned on LeftBag only and frozen before the other videos were re-measured, unchanged. The criterion is unchanged. Even if trial 2 had met it, final proof would require an external dataset never used during development (for example PETS 2006 left-luggage).

### Fixes

Both were measured on LeftBag only, over the 14 s window inside the bag's stay:

- **The dark bag was labelled shadow.** With trial 1's settings it never counted as foreground: 0.0 s foreground, 2.7 s shadow. Shadow detection is now off (`shadows=False`).
- **The slow model absorbed the bag too fast.** A 60 s history absorbed it in about 4 s. With a 600 s history and shadows off, the bag is foreground for the whole 14 s.
- **Startup ghosts.** A warm-up (`warmup_s`: no detection while the background is learnt quickly) and an edge test (`ghost_ratio`: reject a region whose current edges are fewer than ratio × the slow background's edges there) became tunable options.

Tuned on LeftBag over 36 combinations: most events found, then fewest false alarms, then the most conservative values. Frozen at T = 8 s, minimum area 120 px², warm-up 5 s, ghost ratio 1.0.

### Result (RF-DETR person filter, 25 fps): criterion not met

| Video | Set | Result |
|---|---|---|
| LeftBag | tuning | placed (1.12 s), removed (0.4 s), 0 false alarms |
| LeftBox | test | **placed (1.44 s error) and present at end found**, 0 false alarms |
| LeftBag_PickedUp | test | **removal found (0.8 s error)**; placement detected at the right place at 18.0 s, 2.36 s before the XML (20.36 s), so missed and counted as 1 false alarm |
| Fall, Walk2, TwoEnterShop1front, Meet_WalkSplit, Meet_WalkTogether1 | no object | **0 false alarms (raw count 0)** |

Totals: test events **3/4**, 0 false alarms on the no-object videos, 1 on the object videos. CPU time is about 5 s per video minute, excluding RF-DETR.

Sensitivity to T, with the other settings frozen:

| T | Test events | False alarms, no object | False alarms, with object |
|---|---|---|---|
| 2 s | 2/4 | 2 | 4 |
| 3 s | 3/4 | 2 | 3 |
| 5, 8 and 12 s | 3/4 | 0 | 1 |
| 20 s | 0/4 | 0 | 0 |

The result is stable from 5 to 12 s. The only failure is placement timing. The detector dates a placement from the first moment the area differs from the background, which happens while the person carrying the bag arrives. The XML marks the bag once it lies alone. A principled change would date placement from when the area first matches the object's own final appearance, but that would be a third attempt and would also need the external dataset. Review sheets are in `sheets_trial2/`, the blind sheet in `blind_review_trial2.csv`, and the results in `results_trial2.json`.

## Blind test of trial 2 on an unseen video: LeftBag_AtChair (failed)

This is the first test on a video never used during development. `blind_test.py` runs `pilot.detect` unchanged (commit 353dd40), with the frozen parameters read from `results_trial2.json` and the fixed slow-model settings `pilot.TRIAL2_FIXED`. The person filter is computed for this video with the same RF-DETR Nano settings as `persons.py`. `LeftBag_AtChair.mpg` ingests cleanly: 1,116 frames, 44.8 s, XML up to frame 1,114. The criterion is unchanged.

Ground truth: bag placed at 18.36 s at (68,127), removed at 37.20 s.

**Result: 0/2 events found (placement missed, removal missed), 0 false alarms, 0 candidates.** CPU time was 5.2 s per video minute.

Diagnosis, without changing anything:

1. **Contrast.** The bag is placed against the existing dark furniture between the orange chairs. The slow model calls the bag area foreground for only 0.2 s of its 17.5 s stay, and the longest unbroken static run is 0.1 s, against T = 8 s.
2. **Size.** The XML bag box is about 99 px² (median, 63–130), below the frozen 120 px² minimum, so it would have been filtered even if seen.
3. **Person filter.** An RF-DETR person box overlaps the bag area in 57% of the sampled frames during the stay. This is probably furniture detected as a person, as seen in the tracking pilot; that cause is not verified.

Conclusion: the trial 2 settings do not generalise to a small, dark object placed against dark furniture. This held-out result counts more than the 3/4 on development videos. No re-tuning was done on this video, and any further change must be validated on yet another unseen dataset.

## Note: the "XML offset" on TwoEnterShop1front and Meet_WalkSplit was a reader bug

The person-tracking audit traced the reported offsets to a reader that let body landmarks overwrite box centers. The trial 1 reader here uses the same pattern. Impact, checked by rerunning trial 1 with boxes from the direct `<box>` element ([xml_reader_check.py](xml_reader_check.py)):

- The object ground truth is unaffected: no bag box changes in any XML, and those two videos have no objects.
- The trial 1 "XML (perfect)" person filter used wrong person boxes on these two videos, but **its counts do not change**: TwoEnterShop1front 0 false alarms and Meet_WalkSplit 6 (25 fps) and 4 (5 fps), all startup or end ghosts, as with no filter at all. Trial 2 and the blind test used the RF-DETR filter only.

See the [tracking reference audit](../person_tracking/xml_correction.md).
