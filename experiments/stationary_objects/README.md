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
