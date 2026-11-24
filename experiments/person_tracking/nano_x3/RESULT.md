# RF-DETR Nano ×3: entry gate failed, experiment stopped

The protocol ([PROTOCOL.md](PROTOCOL.md)) was committed before any ×3 detection was run (commit 87da75c). Nothing was tuned.

## Stage 1 gate on Walk2 and LeftBag (pooled)

| | ×2 (576×768) | ×3 (864×1152) | Required |
|---|---:|---:|---|
| Small-person recall (√area < 22 px, conf ≥ 0.1, IoU 0.5) | 0.143 (11/77) | 0.130 (10/77) | Δ ≥ +0.15 → **Δ = −0.013, fail** |
| Precision (conf ≥ 0.4, IoU 0.5) | 0.863 | 0.926 | ≥ 0.60 → pass |
| Recall, all people (conf ≥ 0.1, IoU 0.5) | 0.849 | 0.800 | reported only |

Per clip, small-person recall ×2 → ×3: Walk2 0.138 → 0.108 (65 boxes), LeftBag 0.167 → 0.250 (12 boxes). The rerun ×2 detections are identical to the cached ×2 detections.

**Gate failed, so Stage 2 was not run.** Walk3, Meet_Split_3rdGuy and Browse_WhileWaiting1 remain unseen by any detector run. `test.py` is kept unexecuted; it refuses to run while `gate.json` says fail.

The tuning clips contain only 77 small boxes, so this gate has low resolution. However, it asked for a large gain, and the measured change is slightly negative. Overall recall also drops. A further enlargement of the same model does not recover small people.

## CPU time (wall-clock time of the per-frame detection call, 12-core CPU, same session, run one after the other)

| Setting | s CPU per video minute |
|---|---:|
| Nano ×2 | 135.9 |
| Nano ×3 | 375.0 (×2.8) |

The earlier ×2 cache on the same clips recorded 173.7 s per minute, under different machine load.

Files: [gate.json](gate.json), [det_x2.json](det_x2.json), [det_x3.json](det_x3.json), [detect.py](detect.py), [score.py](score.py), [gate.py](gate.py), [test.py](test.py).
