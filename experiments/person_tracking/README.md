# Anonymous person tracks within one video: offline pilot

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

| Detections | Pooled test IDF1 (7 videos) | Same, without the 2 misaligned XML videos (5) | Owner checks | Test ID switches |
|---|---|---|---|---|
| RF-DETR (main) | **0.352** | 0.581 | **2/4** | 4 |
| RF-DETR, no stitching | 0.334 | 0.534 | 2/4 | 7 |
| XML boxes (oracle) | 0.869 | 0.977 | **4/4** | 20 |

Per video with RF-DETR, IDF1: LeftBox 0.766, Rest_FallOnFloor 0.662, LeftBag_AtChair 0.529, Meet_WalkTogether1 0.498, LeftBag_PickedUp 0.479, Meet_WalkSplit 0.009, TwoEnterShop1front 0.002. The tuning videos score Walk2 0.591 and LeftBag 0.528.

Owner test with RF-DETR:

| Video | Set down | Picked up | Result |
|---|---|---|---|
| LeftBag_PickedUp | Person C | **Person D** | failed: the track breaks at the pick-up again, as in the earlier tracking pilot (`experiments/tracking_pilot`) |
| LeftBag_AtChair | Person C | **no label** | failed: the person picking the bag up is not detected near the dark furniture |
| LeftBag (tuning) | Person F | Person H | different labels, as expected |

## Findings

1. **Association works when detection is good.** With XML boxes, stitching and the owner test give 4/4 and IDF1 0.977 on the five well-aligned test videos. The bottleneck is detection, as in the tracking pilot: missed people, furniture, plants and mannequins taken for people, and boxes that change while someone bends.
2. **Stitching helps a little:** IDF1 0.534 → 0.581, and test ID switches 7 → 4.
3. **The XML does not align with our files for two test videos.** On TwoEnterShop1front and Meet_WalkSplit, the XML boxes are offset from the people visible in the frames, by about 20 px vertically on TwoEnterShop and (−12, −7) px on WalkSplit. The offset is not constant, and no time offset explains it. Our `_pts` copies are pixel-identical to the original `.mpg` files (phase correlation 0 px), so the mismatch lies in the annotation itself. RF-DETR IDF1 on these two videos (0.002 and 0.009) therefore measures the annotation, not the tracker. The criterion still fails without them (0.581). This also matters for earlier analyses that compare positions on these two videos; time-based comparisons are unaffected.

Next step: a better person detector for this footage (a larger RF-DETR, which needs approval if it requires new weights, or upscaled input) before any integration. Re-measure against the same criterion on the five well-aligned test videos, plus a held-out set.
