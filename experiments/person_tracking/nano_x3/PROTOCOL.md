# RF-DETR Nano ×3: protocol (written before any ×3 detection was run)

**Question.** Does enlarging the input of the same RF-DETR Nano model from ×2 (576×768) to ×3 (864×1152) recover the small people that cause the held-out failure ([diagnosis](../README.md#root-cause-analysis-of-the-held-out-failure))? Same weights, stride 5, confidence threshold 0.1. The tracker settings are frozen from the Nano ×2 run: activation 0.4, lost buffer 4 s, matching 0.8, stitching 3 s / 20 px (`results_heldout_nano_576x768.json`). Nothing is tuned.

**Definitions** (from the held-out diagnosis): XML boxes come from the direct `<box>` element. Scoring uses every fifth frame. Matching is one-to-one per frame at IoU ≥ 0.5. A person box is **small** when √(w·h) < 22 px. **Recall** counts detections at confidence ≥ 0.1, the cache threshold. **Precision** counts detections at confidence ≥ 0.4, the ByteTrack activation threshold.

## Stage 1: entry gate, on the tuning clips Walk2 and LeftBag only

Pass if both hold, pooled over the two clips:

1. Small-person recall ×3 − ×2 ≥ +0.15 (absolute).
2. ×3 precision ≥ 0.60.

**If the gate fails, stop.** Do not run ×3 on the unseen clips.

## Stage 2: test on three clips never used before

The clips are Walk3, Meet_Split_3rdGuy and Browse_WhileWaiting1. Before scoring, check the alignment: the frame count and the best frame or pixel offset between XML boxes and ×2 detections must be 0 frames and ≤ 2 px. ×2 runs on the same clips as a paired control.

Success requires both:

1. Pooled IDF1 (×3) ≥ 0.70.
2. Pooled small-person recall (×3) ≥ 0.50.

## Reported in every case

CPU time per video minute for ×2 and ×3, using the same definition as the README: wall-clock time of the per-frame detection call. Even on success, tracking stays experimental until it is shown to help event reconstruction.
